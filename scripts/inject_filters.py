#!/usr/bin/env python3

import json

import defusedxml.ElementTree as ET

tree = ET.parse("data/mailfilter.xml")
root = tree.getroot()
if root is None:
    raise SystemExit("mailfilter.xml has no root element")

data = {}
for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
    from_tag = entry.find("{http://schemas.google.com/apps/2006}property[@name='from']")
    label_tag = entry.find("{http://schemas.google.com/apps/2006}property[@name='label']")
    if from_tag is None or label_tag is None:
        continue
    from_value = from_tag.get("value")
    label = label_tag.get("value")
    if from_value is None or label is None:
        continue
    senders = from_value.split(" OR ")
    for sender in senders:
        if sender not in data:
            data[sender] = {}
        if label not in data[sender]:
            data[sender][label] = 0
        data[sender][label] += 1

with open("db/validated_classification_db.json", "w") as f:
    json.dump(data, f, indent=4)
