#!/usr/bin/env bash

API_URL="https://1gqsgn39tk.execute-api.ap-southeast-2.amazonaws.com/Prod/video/"
VIDEO_URL="https://www.youtube.com/watch?v=RjEdmrxjIHQ"

curl -d "{\"url\":\"${VIDEO_URL}\"}" -H "Content-Type: application/json" -X POST ${API_URL}