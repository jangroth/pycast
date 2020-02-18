import json
from unittest.mock import MagicMock

import pytest

from src.app import Downloader

GOOD_EVENT = '''
{
    "url":"https://www.youtube.com/watch?v=RjEdmrxjIHQ"
}
'''


@pytest.fixture
def good_event():
    base_event = json.loads(GOOD_EVENT)
    base_event['body'] = '{\"url\":\"https://www.ccc.de\"}'
    return base_event


@pytest.fixture()
def dld():
    the_object = Downloader.__new__(Downloader)
    the_object.logger = MagicMock()
    the_object.telegram = MagicMock()
    return the_object


def test_should_retrieve_url_from_incoming_event(dld, good_event):
    assert dld._extract_url_from_event(good_event) == 'https://www.youtube.com/watch?v=RjEdmrxjIHQ'
