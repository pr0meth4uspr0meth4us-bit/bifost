#!/bin/bash

export PYTHONPATH=$PYTHONPATH:.
python bot/main.py &

exec gunicorn --bind 0.0.0.0:8000 run:app