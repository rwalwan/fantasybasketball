"""News blurbs are read by DeepSeek V4.1 Flash (eval Oct 28); articles and explanations stay on Haiku."""
import os, sys
for k in ("OPENROUTER_MODEL", "OPENROUTER_MODEL_NEWS", "OPENROUTER_MODEL_ADVICE"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import news
assert news.NEWS_MODEL == "deepseek/deepseek-v4.1-flash-1017"
assert news.ADVICE_MODEL == news.MODEL == "anthropic/claude-haiku-5.5"
src = open(news.__file__).read()
assert src.count("llm_json(NEWS_PROMPT") == src.count("model=NEWS_MODEL") >= 2, "every news call uses NEWS_MODEL"
print("ok: news model")
