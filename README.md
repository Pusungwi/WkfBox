WkfBox
======

What the heck is this?
----------------------

This is a simple storage to make ease of viewing Wkfs. Wkf is 짤 in Korean (Type it in English mode), which means pictures for posts/articles.

Can I run it?
-------------

This is only tested on Python 2.7.3, so I can't guarantee it will run on other versions.

Are there any prequisites to run this?
--------------------------------------

You need following Python modules to run it:

- [Flask](http://flask.pocoo.org)
- [SQLAlchemy](http://www.sqlalchemy.org)
- [Python Imaging Library](http://www.pythonware.com/products/pil/)
- [Unidecode](http://pypi.python.org/pypi/Unidecode/)

How to run?
-----------

Run it as same as other WSGI applications. First, copy config_sample.py to config.py and change it as you like. You can run a development server by following command:

```
$ python WkfBox.py
```

If you have given +x permission to WkfBox.py, you can easily do the same thing:

```
$ ./WkfBox.py
```

License
-------

This project follows [WTFPL](http://sam.zoy.org/wtfpl/). Please check out [COPYING](https://github.com/Saberre/WkfBox/blob/master/COPYING) file.