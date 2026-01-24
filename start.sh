#!/bin/bash

# use 0.0.0.0 for HF Spaces, localhost for local dev
if [ -n "$SPACE_ID" ]; then
    HOST="0.0.0.0"
else
    HOST="localhost"
fi

# start fastapi in background
uvicorn src.api:app --host $HOST --port 8000 &

# wait for api to be ready
sleep 3

# start streamlit on port 7860
streamlit run src/frontend.py --server.port 7860 --server.address $HOST
