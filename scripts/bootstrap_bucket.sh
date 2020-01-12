#!/usr/bin/env bash

ARTIFACT_BUCKET_NAME=pycast-artifacts

aws s3 mb s3://${ARTIFACT_BUCKET_NAME}
