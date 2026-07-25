#!/usr/bin/env python3
import json
json.dump({"tasks": [], "next_id": 1}, open("backend/data/tasks.json", "w", encoding="utf-8"))
print("tasks.json cleared")
