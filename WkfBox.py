#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This program is free software. It comes without any warranty, to
# the extent permitted by applicable law. You can redistribute it
# and/or modify it under the terms of the Do What The Fuck You Want
# To Public License, Version 2, as published by Sam Hocevar. See
# http://sam.zoy.org/wtfpl/COPYING for more details.

# Imports
import math
import os
import re
import uuid

from flask import Flask, abort, redirect, request, send_file, render_template, url_for

from werkzeug.utils import secure_filename

from sqlalchemy import create_engine, Table, Column, Integer, String, ForeignKey
from sqlalchemy.orm import scoped_session, sessionmaker, relationship
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.sql.expression import desc, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.associationproxy import association_proxy

from unidecode import unidecode

from PIL import Image

import config

# Helpers
_punct_re = re.compile(r'[\t !"#$%&\'()*\-/<=>?@\[\\\]^_`{|},.]+')

def slugify(text, delim=u'-'):
  """Generates an ASCII-only slug."""
  result = []
  for word in _punct_re.split(text.lower()):
      result.extend(unidecode(word).split())
  return unicode(delim.join(result))

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

# Database
engine = create_engine(config.DB_CONNECTION_STRING, echo=config.DEBUG)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

def init_db():
  Base.metadata.drop_all(bind=engine)
  Base.metadata.create_all(bind=engine)

# Models
class Category(Base):
  __tablename__ = 'categories'
  
  id = Column(Integer, primary_key=True)
  slug = Column(String, nullable=False, unique=True)
  name = Column(String, nullable=False)
  pictures = relationship('Picture', backref='category')
  
  def __init__(self, name, slug=None):
    self.name = name
    self.slug = slug or slugify(self.name)

class Keyword(Base):
  __tablename__ = 'keywords'
  
  id = Column(Integer, primary_key=True)
  slug = Column(String, nullable=False, unique=True)
  name = Column(String, nullable=False)
  
  def __init__(self, name):
    self.name = name
    self.slug = slugify(self.name)

class Picture(Base):
  __tablename__ = 'pictures'
  
  id = Column(Integer, primary_key=True)
  category_id = Column(Integer, ForeignKey(Category.id))
  filename = Column(String, nullable=False)
  original_filename = Column(String)
  thumbnail = Column(String, nullable=False)
  episode = Column(Integer)
  kw = relationship('Keyword', secondary=lambda: association_table, backref='pictures')
  
  keywords = association_proxy('kw', 'name')

  def __init__(self, filename, thumbnail, original_filename=None):
    self.filename = filename
    self.thumbnail = thumbnail
    self.original_filename = original_filename

association_table = Table('pictures_keywords', Base.metadata,
  Column('picture_id', Integer, ForeignKey(Picture.id)),
  Column('keyword_id', Integer, ForeignKey(Keyword.id))
)

app = Flask(__name__)
app.config.from_object(config)

@app.teardown_request
def shutdown_session(exception=None):
  db_session.remove()

@app.route('/favicon.ico')
def favicon():
  abort(404)

@app.route('/new/picture', methods=['GET', 'POST'])
def upload():
  if request.method == 'POST' and 'image' in request.files:
    # Necessary variables
    uploaded_image = request.files['image']
    original_filename = secure_filename(uploaded_image.filename)
    fileext = os.path.splitext(original_filename)[1]
    if not fileext in app.config['ALLOWED_EXTS']:
      abort(400)
    filename = str(uuid.uuid4())
    thumbnail = filename + '.thumb.jpg'

    # Find category
    category = None
    if request.form['category']:
      try:
        category = Category.query.filter_by(name=request.form['category']).one()
      except MultipleResultsFound:
        abort(400)
      except NoResultFound:
        try:
          category = Category.query.filter_by(slug=request.form['category']).one()
        except NoResultFound:
          abort(400)

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
    picture.category_id = category.id if category else None
    picture.episode = request.form.get('episode', None, int)
    db_session.add(picture)
    db_session.commit()

    return redirect('/')

  return render_template('upload.html')

@app.route('/new/category', methods=['GET', 'POST'])
def add_category():
  if request.method == 'POST':
    category = Category(request.form['name'], request.form['slug'] or None)
    db_session.add(category)
    db_session.commit()

    return redirect('/' + category.slug)
  return render_template('category.html')

@app.route('/<category_slug>/:edit', methods=['GET', 'POST'])
def edit_category(category_slug):
  if request.method == 'POST':
    try:
      category = Category.query.filter_by(slug=category_slug).one()
    except NoResultFound:
      abort(404)

    category.name = request.form['name'] or abort(400)
    category.slug = request.form['slug'] or slugify(category.name)

    db_session.commit()

    return redirect(url_for('list', category_slug=category.slug))

  try:
    category = Category.query.filter_by(slug=category_slug).one()
  except NoResultFound:
    abort(404)

  return render_template('category.html', category=category)

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
  filename = picture.thumbnail if 'thumb' in request.args \
             else picture.filename
  return send_file(os.path.join(app.config['UPLOAD_DIRECTORY'], filename))

@app.route('/:<int:id>/delete')
def delete(id):
  try:
    picture = Picture.query.filter_by(id=id).one()
  except NoResultFound:
    abort(404)
  db_session.delete(picture)
  db_session.commit()

  return redirect('/')

@app.route('/', defaults={'category_slug': None, 'episode': None})
@app.route('/<category_slug>', defaults={'episode': None})
@app.route('/<category_slug>/:<int:episode>')
def list(category_slug=None, episode=None):
  page = request.args.get('page',  1, int)
  range_start = (page - 1) * app.config['PER_PAGE']
  range_end = page * app.config['PER_PAGE']
  category = None

  pictures = Picture.query
  if category_slug is not None:
    try:
      category = Category.query.filter_by(slug=category_slug).one()
    except NoResultFound:
      abort(404)
    category_name = category.name
    pictures = pictures.filter_by(category_id=category.id)
    if episode is not None:
      pictures = pictures.filter_by(episode=episode)

  count = pictures.count()
  total_page = math.ceil(float(count) / app.config['PER_PAGE'])
  if range_start > count:
    abort(404)

  pictures = pictures.order_by(desc(Picture.id))[range_start:range_end]
  return render_template('list.html', pictures=pictures, category=category
                                    , episode=episode, page=page, total_page=total_page)

if __name__ == '__main__':
  app.run()
