#!/bin/bash
set -e

if [ "x$1" == "x" ]
then
  echo "Usage: $0 init && source ~/.bashrc && pythonbrew install --update 2.7.3 && pythonbrew switch 2.7.3 && pythonbrew venv init && pythonbrew venv create lightning && pythonbrew venv use lightning && $0 install"
  exit 1
elif [ $1 == "init" ]
then
  curl -kL http://xrl.us/pythonbrewinstall | bash
  echo "[[ -s $HOME/.pythonbrew/etc/bashrc ]] && source $HOME/.pythonbrew/etc/bashrc" >> "$HOME/.bashrc"
  source "$HOME/.bashrc"
elif [ $1 == "install" ]
then
  # For lightning
  pip install twisted==12.2.0
  pip install cyclone==1.0_rc15
  pip install --upgrade docopt
  pip install --upgrade pyyaml
  pip install --upgrade requests
  pip install --upgrade iso8601
  pip install --upgrade python_faker
  pip install pyopenssl==0.13

  pip install --upgrade pyres
  pip install --upgrade pyodbc
  pip install --upgrade bleach
  pip install --upgrade python-dateutil
  pip install --upgrade httplib2
  pip install --upgrade newrelic
  pip install --upgrade prettytable
  pip install --upgrade phonenumbers
  pip install --upgrade bidict


  # For the test suite
  pip install beautifulsoup4==4.1.3
  pip install --upgrade coverage
  pip install --upgrade pylint
  pip install --upgrade mock

  # For the console
  pip install --upgrade pycket
  pip install tornado-redis

  DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
  easy_install --upgrade ${DIR}/bin/python_eggs/twistar-3.2-py2.7.egg
  easy_install --upgrade ${DIR}/bin/python_eggs/oauth2-1.5.211-py2.7.egg
fi
