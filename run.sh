#!/bin/bash
export PYTHONPATH=$PYTHONPATH:.
# Just run Flask. The bot lives inside it now.
exec gunicorn --bind 0.0.0.0:8000 run:app