import json
from unittest.mock import MagicMock

import pytest

from app import Observer

BASE_EVENT = '''
{
  "resource": "/video",
  "headers": {
    "Accept": "*/*"
  },
  "multiValueHeaders": {
    "Accept": [
      "*/*"
    ]
  },
  "requestContext": {
    "resourceId": "am7t8d"
  },
  "apiId": "chw6q7n9oc"
}
'''


@pytest.fixture
def good_event():
    base_event = json.loads(BASE_EVENT)
    base_event['body'] = '{\"url\":\"https://www.ccc.de\"}'
    return base_event


@pytest.fixture
def bad_event():
    base_event = json.loads(BASE_EVENT)
    base_event['foo'] = 'bar'
    return base_event


@pytest.fixture()
def obs():
    the_object = Observer.__new__(Observer)
    the_object.logger = MagicMock()
    the_object.telegram = MagicMock()
    return the_object


def test_return_200_on_good_event(good_event, obs):
    obs._start_state_machine = MagicMock()

    result = obs.handle_event(good_event)

    obs._start_state_machine.assert_called_once_with({'url': 'https://www.ccc.de'})
    assert result['statusCode'] == 200


def test_return_500_on_bad_event(bad_event, obs):
    obs._start_state_machine = MagicMock()

    result = obs.handle_event(good_event)

    obs._start_state_machine.assert_not_called()
    assert result['statusCode'] == 500
