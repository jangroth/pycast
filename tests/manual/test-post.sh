#!/usr/bin/env bash

API_URL=$(aws cloudformation describe-stacks --stack-name pycast --output text --query "Stacks[].Outputs[?OutputKey=='PyCastApi'].OutputValue")
VIDEO_URL="https://www.youtube.com/watch?v=RjEdmrxjIHQ"
#VIDEO_URL="https://www.youtube.com/watch?v=9HfzcqeS2SU"
#VIDEO_URL="https://www.youtube.com/watch?v=MlLkhWarrYQ"

curl -d "{\"url\":\"${VIDEO_URL}\"}" -H "Content-Type: application/json" -X POST ${API_URL}
