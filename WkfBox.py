#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This program is free software. It comes without any warranty, to
# the extent permitted by applicable law. You can redistribute it
# and/or modify it under the terms of the Do What The Fuck You Want
# To Public License, Version 2, as published by Sam Hocevar. See
# http://sam.zoy.org/wtfpl/COPYING for more details.

# Imports
from functools import wraps
import math
import os
import re
import sys
import uuid

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.wtf import ValidationError, Form, StringField as _StringField, PasswordField, FileField, EqualTo, DataRequired, Optional, Regexp, NumberRange, FileRequired
from flask.ext.wtf.html5 import IntegerField as _IntegerField

from werkzeug.utils import secure_filename

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import desc, func
from sqlalchemy.ext.associationproxy import association_proxy

from wtforms.ext.sqlalchemy.fields import QuerySelectField
from wtforms.ext.sqlalchemy.validators import Unique

from unidecode import unidecode

from PIL import Image

import bcrypt

import config

#region Application Initialization
app = Flask(__name__)
app.config.from_object(config)
db = SQLAlchemy(app)
#endregion

#region Helpers
_punct_re = re.compile(r'[\t !"#$%&\'()*\-/<=>?@\[\\\]^_`{|},.]+')

def slugify(text, delim='-'):
  """Generates an ASCII-only slug."""
  result = []
  for word in _punct_re.split(text.lower()):
      result.extend(unidecode(word).split())
  return str(delim.join(result))

def rebuild_thumbnail():
  pictures = Picture.query.all()
  for picture in pictures:
    try:
      os.unlink(os.path.join(config.UPLOAD_DIRECTORY, picture.thumbnail))
    except OSError:
      pass
    with open(os.path.join(config.UPLOAD_DIRECTORY, picture.filename)) as fp:
      image = Image.open(fp)
      image.thumbnail(config.THUMBNAIL_SIZE, Image.ANTIALIAS)
      image.save(os.path.join(config.UPLOAD_DIRECTORY, picture.thumbnail))

def init_db():
  print("initializing DB...")
  db.drop_all()
  db.create_all()
#endregion

#region Decorators
def login_required(f):
  @wraps(f)
  def wrapper(*args, **kwargs):
    if not 'user' in session:
      flash('You have to be logged in to continue.')
      return redirect(url_for('login'))
    return f(*args, **kwargs)
  return wrapper
#endregion

#region Models
class User(db.Model):
  __tablename__ = 'users'

  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String, nullable=False, unique=True)
  password = db.Column(db.String, nullable=False)
  pictures = db.relationship('Picture', backref='user')

  def __init__(self, username, password):
    self.username = username
    self.password = password

class Category(db.Model):
  __tablename__ = 'categories'
  
  id = db.Column(db.Integer, primary_key=True)
  slug = db.Column(db.String, nullable=False, unique=True)
  name = db.Column(db.String, nullable=False)
  pictures = db.relationship('Picture', backref='category')
  
  def __init__(self, name, slug=None):
    self.name = name
    self.slug = slug or slugify(self.name)

  def __str__(self):
    return self.name

class Keyword(db.Model):
  __tablename__ = 'keywords'
  
  id = db.Column(db.Integer, primary_key=True)
  slug = db.Column(db.String, nullable=False, unique=True)
  name = db.Column(db.String, nullable=False)

  def __init__(self, name):
    self.name = name
    self.slug = slugify(self.name)

class Picture(db.Model):
  __tablename__ = 'pictures'
  
  id = db.Column(db.Integer, primary_key=True)
  user_id = db.Column(db.Integer, db.ForeignKey(User.id))
  category_id = db.Column(db.Integer, db.ForeignKey(Category.id))
  filename = db.Column(db.String, nullable=False)
  original_filename = db.Column(db.String)
  thumbnail = db.Column(db.String, nullable=False)
  episode = db.Column(db.Integer)
  kw = db.relationship('Keyword', secondary=lambda: association_table, backref='pictures')
  
  keywords = association_proxy('kw', 'name')

  def __init__(self, filename, thumbnail, original_filename=None):
    self.filename = filename
    self.thumbnail = thumbnail
    self.original_filename = original_filename

association_table = db.Table('pictures_keywords', db.metadata,
  db.Column('picture_id', db.Integer, db.ForeignKey(Picture.id)),
  db.Column('keyword_id', db.Integer, db.ForeignKey(Keyword.id))
)
#endregion

#region Forms
class StringField(_StringField):
  def __call__(self, **kwargs):
    if 'required' in self.flags:
      kwargs['required'] = 'required'
    return super(StringField, self).__call__(**kwargs)

class IntegerField(_IntegerField):
  def __call__(self, **kwargs):
    for validator in self.validators:
      if isinstance(validator, NumberRange):
        if validator.min:
          kwargs['min'] = validator.min
        if validator.max:
          kwargs['max'] = validator.max
        break
    return super(IntegerField, self).__call__(**kwargs)

class SlugField(StringField):
  def __init__(self, source, **kwargs):
    self.source = source
    super(SlugField, self).__init__(**kwargs)

  def pre_validate(self, form):
    if not self.data:
      self.data = slugify(form[self.source].data)

class FileAllowed(object):
  def __init__(self, message=None):
    if message:
      self.message = message
    else:
      self.message = 'Only ' + ', '.join(app.config['ALLOWED_EXTS']) + ' files are allowed.'

  def __call__(self, form, field):
    if not field.has_file():
      return
    if not os.path.splitext(field.data.filename)[-1] in app.config['ALLOWED_EXTS']:
      raise ValidationError(self.message)

class SignupForm(Form):
  username = StringField('Username', validators=[
    DataRequired(),
    Regexp('^[A-Za-z0-9\-_]+$', message='Only alphabets, numbers, hyphen, and underscore are allowed.'),
    Unique(lambda: db.session, User, User.username)
  ])
  password = PasswordField('Password', validators=[DataRequired()])
  password_confirmation = PasswordField('Confirm Password', validators=[DataRequired(),
    EqualTo('password', 'Password confirmation is different from password.')
  ])

class LoginForm(Form):
  username = StringField('Username', validators=[
    DataRequired(),
    Regexp('^[A-Za-z0-9\-_]+$', message='Only alphabets, numbers, hyphen, and underscore are allowed.')
  ])
  password = PasswordField('Password', validators=[DataRequired()])

class CategoryForm(Form):
  name = StringField('Name', validators=[DataRequired()])
  slug = SlugField('name', label='Slug', validators=[
    Regexp('^[0-9a-z\-]+$', message='Only lowercase alphabets, numbers, and hyphen are allowed.'),
    Unique(lambda: db.session, Category, Category.slug)
  ])

class UploadForm(Form):
  picture = FileField('Image', validators=[
    FileRequired('This field is required.'),
    FileAllowed()
  ])
  category = QuerySelectField(query_factory=lambda: Category.query.order_by(Category.name),
                              allow_blank=True)
  episode = IntegerField('Episode', validators=[Optional(strip_whitespace=False), NumberRange(1)])

#region Views
@app.errorhandler(404)
def error_404(e):
  return render_template('404.html'), 404

@app.route('/favicon.ico')
def favicon():
  abort(404)

@app.route('/login', methods=['GET', 'POST'])
def login():
  form = LoginForm()
  error = None
  if form.validate_on_submit():
    try:
      user = User.query.filter_by(username=form.username.data).one()
    except NoResultFound:
      user = None
    if user and user.password == bcrypt.hashpw(form.password.data, user.password):
      session['user'] = user.id
      flash('Successfully logged in.')
      return redirect(url_for('list'))
    error = 'Invalid username or password.'
  return render_template('login.html', form=form, error=error)

@app.route('/logout')
@login_required
def logout():
  session.pop('user', None)
  flash('Successfully logged out.')
  return redirect(request.referrer or url_for('list'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
  form = SignupForm()
  if form.validate_on_submit():
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(form.password.data, salt)

    user = User(form.username.data, hashed_password)

    db.session.add(user)
    db.session.commit()

    return redirect(url_for('list'))
  return render_template('signup.html', form=form)

@app.route('/new/picture', methods=['GET', 'POST'])
@login_required
def upload():
  form = UploadForm()
  if form.validate_on_submit():
    # Necessary variables
    uploaded_image = form.picture.data
    original_filename = secure_filename(uploaded_image.filename)
    fileext = os.path.splitext(original_filename)[1]
    filename = str(uuid.uuid4())
    thumbnail = filename + '.thumb.jpg'

    # Save thumbnail
    image = Image.open(uploaded_image.stream)
    image.thumbnail(app.config['THUMBNAIL_SIZE'], Image.ANTIALIAS)
    image.save(os.path.join(app.config['UPLOAD_DIRECTORY'], thumbnail))

    # Save original image
    uploaded_image.stream.seek(0)
    uploaded_image.save(os.path.join(app.config['UPLOAD_DIRECTORY'],
      filename + fileext))

    # Save to database
    picture = Picture(filename + fileext, thumbnail, original_filename)
    picture.user_id = session['user']
    picture.category = form.category.data
    picture.episode = form.episode.data or None
    db.session.add(picture)
    db.session.commit()

    return redirect(url_for('show', id=picture.id))
  return render_template('upload.html', form=form)

@app.route('/new/category', methods=['GET', 'POST'])
@login_required
def add_category():
  form = CategoryForm()
  if form.validate_on_submit():
    category = Category(request.form['name'], request.form['slug'] or None)
    db.session.add(category)
    db.session.commit()

    return redirect(url_for('list', category_slug=category.slug))
  return render_template('category.html', form=form)

@app.route('/<category_slug>/:edit', methods=['GET', 'POST'])
@login_required
def edit_category(category_slug):
  try:
    category = Category.query.filter_by(slug=category_slug).one()
  except NoResultFound:
    abort(404)

  form = CategoryForm(obj=category)
  if form.validate_on_submit():
    try:
      category = Category.query.filter_by(slug=category_slug).one()
    except NoResultFound:
      abort(404)

    category.name = form.name.data
    category.slug = form.slug.data or slugify(category.name)

    db.session.commit()

    return redirect(url_for('list', category_slug=category.slug))
  return render_template('category.html', form=form)

@app.route('/:r')
def random():
  picture = Picture.query.order_by(func.random())[0]
  return redirect(url_for('show', id=picture.id))

@app.route('/:<int:id>')
def show(id):
  try:
    picture = Picture.query.filter_by(id=id).one()
  except NoResultFound:
    abort(404)

  if 'type' in request.args:
    filename = picture.thumbnail if request.args['type'] == 'thumb' \
             else picture.filename
    return send_file(os.path.join(app.config['UPLOAD_DIRECTORY'], filename))
  return render_template('show.html', picture=picture)

@app.route('/:<int:id>/edit')
@login_required
def edit(id):
  pass

@app.route('/:<int:id>/delete')
@login_required
def delete(id):
  try:
    picture = Picture.query.filter_by(id=id).one()
  except NoResultFound:
    abort(404)
  db.session.delete(picture)
  db.session.commit()

  return redirect('/')

@app.route('/', defaults={'category_slug': None, 'episode': None})
@app.route('/<category_slug>', defaults={'episode': None})
@app.route('/<category_slug>/:<int:episode>')
def list(category_slug=None, episode=None):
  page = request.args.get('page', 1, int)
  range_start = (page - 1) * app.config['PER_PAGE']
  range_end = page * app.config['PER_PAGE']
  category = None

  pictures = Picture.query
  if category_slug:
    try:
      category = Category.query.filter_by(slug=category_slug).one()
    except NoResultFound:
      abort(404)
    pictures = pictures.filter_by(category_id=category.id)
    if episode:
      pictures = pictures.filter_by(episode=episode)

  count = pictures.count()
  total_page = math.ceil(float(count) / app.config['PER_PAGE'])
  if range_start > count:
    abort(404)

  pictures = pictures.order_by(desc(Picture.id))[range_start:range_end]
  return render_template('list.html', pictures=pictures, category=category
                                    , episode=episode, page=page, total_page=total_page)
#endregion

if __name__ == '__main__':
  app.run(sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1')
