#!/usr/bin/env bash

API_URL="https://5nch3ayhad.execute-api.ap-southeast-2.amazonaws.com/Prod/video/"
VIDEO_URL="https://www.youtube.com/watch?v=9bZkp7q19f0"

curl -d "{\"url\":\"${VIDEO_URL}\"}" -H "Content-Type: application/json" -X POST ${API_URL}
