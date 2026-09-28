"""Second opinion per sender: Gemma classifies each scanned sender once (spec section 1.2)."""

from loguru import logger

from .taxonomy import llm_sender_part, llm_sender_static_prompt, parse_category_number


def crosscheck_senders(
    senders: dict, llm, done: dict, batch_size: int = 8, save_every: int = 100, on_save=None
) -> dict:
    """Gemma category (or None if unreadable) for every sender not in `done`, biggest senders first."""
    results = dict(done)
    todo = sorted(
        (s for s in senders if s not in results), key=lambda s: -sum(senders[s]["categories"].values())
    )
    static = llm_sender_static_prompt()
    for start in range(0, len(todo), save_every):
        chunk = todo[start : start + save_every]
        parts = [llm_sender_part(senders[s]["name"], s, senders[s]["subjects"]) for s in chunk]
        answers = llm.classify_batch(static, parts, batch_size=batch_size)
        for sender, answer in zip(chunk, answers, strict=True):
            results[sender] = parse_category_number(answer)
        if on_save:
            on_save(results)
        logger.info(f"Crosscheck: {len(results)}/{len(senders)} senders")
    return results
