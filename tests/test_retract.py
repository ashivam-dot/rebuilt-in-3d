from studio import youtube


class Call:
    def __init__(self, result=None, log=None, body=None):
        self.result, self.log, self.body = result, log, body

    def execute(self):
        if self.log is not None:
            self.log.append(self.body)
        return self.result


class Videos:
    def __init__(self, items):
        self.items, self.updates = items, []

    def list(self, **kw):
        return Call({"items": [v for v in self.items if v["id"] in kw["id"].split(",")]})

    def update(self, part, body):
        return Call(log=self.updates, body=body)


class API:
    def __init__(self, items):
        self.v = Videos(items)

    def videos(self):
        return self.v


def video(vid, privacy, publish_at=None, channel=youtube.CHANNEL_ID):
    status = {"privacyStatus": privacy, **({"publishAt": publish_at} if publish_at else {})}
    return {"id": vid, "snippet": {"channelId": channel}, "status": status}


def test_retracted_uploads_go_private_once_and_a_scheduled_one_loses_its_publish_time():
    api = API([video("B3TumXzN63I", "public"), video("MAKHg-RUtRw", "private", "2026-10-17T02:00:00Z"),
               video("B7Bn2Yhnlp8", "private"), video("Pyn07q8sFcs", "public", channel="UCother")])
    done = youtube.retract(api)
    assert [b["id"] for b in api.v.updates] == ["B3TumXzN63I", "MAKHg-RUtRw"]
    assert all(b["status"]["privacyStatus"] == "private" and "publishAt" not in b["status"] for b in api.v.updates)
    assert len(done) == 2 and "mid-ocean-ridge" in done[0]
