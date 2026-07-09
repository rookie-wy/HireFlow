#!/bin/bash
export $(cat .env.example | xargs)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000