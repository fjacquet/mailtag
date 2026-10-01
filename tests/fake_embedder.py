"""Stands in for mailtag.mlx_provider.MLXEmbedder in tests: no download, no network."""

import numpy as np

WORDS = ("pizza", "impot", "train")


class FakeEmbedder:
    """One axis per keyword of WORDS found in the text, plus a constant axis so no vector is zero."""

    instances: list["FakeEmbedder"] = []
    fail_load = False

    def __init__(self, model_name: str = "fake"):
        self.model_name = model_name
        self.prefixes: list[str] = []
        self.fail = 0  # number of encode calls that raise
        FakeEmbedder.instances.append(self)

    @property
    def model(self):
        if FakeEmbedder.fail_load:
            raise OSError("no cached weights")
        return self

    def encode(self, texts, prefix="search_document: "):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("encode failed")
        self.prefixes.append(prefix)
        return np.array([[float(w in t.lower()) for w in WORDS] + [0.1] for t in texts])
