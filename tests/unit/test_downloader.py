import json
from unittest.mock import MagicMock

import pytest

from src.app import Downloader, VideoInformation

GOOD_EVENT = '''
{
    "url":"https://www.youtube.com/watch?v=1234567"
}
'''

VIDEO_INFORMATION = VideoInformation(video_id='video_id', title='title', views='views', rating='rating', description='description')


@pytest.fixture
def good_event():
    event = json.loads(GOOD_EVENT)
    event['body'] = '{\"url\":\"https://www.ccc.de\"}'
    return event


@pytest.fixture()
def dld():
    the_object = Downloader.__new__(Downloader)
    the_object.logger = MagicMock()
    the_object.telegram = MagicMock()
    return the_object


def test_should_retrieve_url_from_incoming_event(dld, good_event):
    assert dld._extract_url_from_event(good_event) == 'https://www.youtube.com/watch?v=1234567'
