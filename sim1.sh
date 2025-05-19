curl -X POST http://localhost:1025 \
  -H "Content-Type: application/json" \
  -d '{
    "alarm": {
      "name": "test-auto",
      "sources": [
        {"device": "68D79AE5ABE9", "type": "include"},
        {"device": "E063DA01A4CE", "type": "include"}
      ],
      "conditions": [
        {"condition": {"type": "is", "source": "vehicle"}},
        {"condition": {"type": "is", "source": "package"}},
        {"condition": {"type": "is", "source": "animal"}},
        {"condition": {"type": "is", "source": "person"}}
      ],
      "triggers": [
        {
          "key": "vehicle",
          "device": "68D79AE5ABE9",
          "zones": {"loiter": [], "zone": [1], "line": []},
          "eventId": "6825b65401986503e417318f",
          "timestamp": 1747301972418
        }
      ],
      "eventPath": "/protect/events/event/6825b65401986503e417318f",
      "eventLocalLink": "https://10.30.1.118/protect/events/event/6825b65401986503e417318f"
    },
    "timestamp": 1747301973486
  }'
