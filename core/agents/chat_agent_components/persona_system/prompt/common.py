import os

def get_project_root() -> str:
    try:
        here = os.path.abspath(os.path.dirname(__file__))
        # prompt -> persona_system -> chat_agent_components -> agents -> core -> root
        return os.path.normpath(os.path.join(here, "..", "..", "..", "..", ".."))
    except Exception:
        return os.getcwd()
