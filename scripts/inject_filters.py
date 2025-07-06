#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import json

tree = ET.parse('data/mailfilter.xml')
root = tree.getroot()

data = {}
for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
    from_tag = entry.find("{http://schemas.google.com/apps/2006}property[@name='from']")
    label_tag = entry.find("{http://schemas.google.com/apps/2006}property[@name='label']")
    if from_tag is not None and label_tag is not None:
        senders = from_tag.get('value').split(' OR ')
        label = label_tag.get('value')
        for sender in senders:
            if sender not in data:
                data[sender] = {}
            if label not in data[sender]:
                data[sender][label] = 0
            data[sender][label] += 1

with open('db/validated_classification_db.json', 'w') as f:
    json.dump(data, f, indent=4)
