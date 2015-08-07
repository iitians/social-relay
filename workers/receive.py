from _socket import timeout
import json
import logging
from federation.controllers import handle_receive
from federation.entities.base import Post
from federation.exceptions import NoSuitableProtocolFoundError
import redis
import requests
from requests.exceptions import ConnectionError, Timeout

from social_relay import config


r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB)


def get_pod_preferences():
    return r.hgetall("pod_preferences")


def pods_who_want_all():
    pods = []
    for pod, data in get_pod_preferences().items():
        data = json.loads(data.decode("utf-8"))
        if data["subscribe"] and data["scope"] == "all":
            pods.append(pod)
    return pods


def send_payload(host, payload):
    """Post payload to host, try https first, fall back to http.

    Return True or False, depending on success of operation.
    Timeouts or connection errors will not be raised.
    """
    logging.info("Sending payload to %s" % host)
    try:
        try:
            response = requests.post("https://%s/receive/public" % host, data=payload, timeout=10)
        except timeout:
            response = False
        if not response or response.status_code != 200:
            response = requests.get("http://%s/receive/public" % host, data=payload, timeout=10)
            if response.status_code != 200:
                return False
    except (ConnectionError, Timeout):
        return False
    return True


def process(payload):
    """Open payload and route it to any pods that might be interested in it."""
    try:
        sender, protocol_name, entities = handle_receive(payload, skip_author_verification=True)
        logging.debug("sender=%s, protocol_name=%s, entities=%s" % (sender, protocol_name, entities))
    except NoSuitableProtocolFoundError:
        logging.warning("No suitable protocol found for payload")
        return
    if protocol_name != "diaspora":
        logging.warning("Unsupported protocol: %s, sender: %s" % (protocol_name, sender))
        return
    if not entities:
        logging.warning("No entities in payload")
        return
    send_to_pods = pods_who_want_all()
    send_to_pods += config.ALWAYS_FORWARD_TO_HOSTS
    for entity in entities:
        logging.info("Entity: %s" % entity)
        # We only care about posts atm
        if isinstance(entity, Post):
            # Send out
            # TODO: add scope: tags checks
            for pod in send_to_pods:
                send_payload(pod, payload)
