# PyCast

Convert YouTube videos into podcast.

# Setup

## Telegram Bot
* Create telegram bot -> [https://core.telegram.org/bots](https://core.telegram.org/bots)

## Python Environment
* Create `pipenv` environment -> `pipenv --python 3.7`
* Open `pipenv` shell -> `pipenv shell`
* Install `pipenv` dependencies -> `pipenv install --def`

## AWS Stacks
* Bootstrap secrets -> `./scripts/bootstrap-secrets`
* Bootstrap code bucket -> `./scripts/bootstrap-bucket`
* Build AWS-SAM project -> `sam build`
* Deploy AWS-SAM project -> `sam deploy`


