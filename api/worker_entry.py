import runpod

from .handler import handle_event


def worker(event):
    return handle_event(event)


if __name__ == "__main__":
    runpod.serverless.start({"handler": worker})
