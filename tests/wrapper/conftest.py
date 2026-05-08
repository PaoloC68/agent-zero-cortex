"""Sourced from frdel/agent-zero@2613fac0:helpers/extension.py:212-220, helpers/projects.py:get_context_project_name, helpers/dirty_json.py. Update if upstream changes."""
from __future__ import annotations

import sys
from types import ModuleType


def pytest_configure(config):
    """Register stub helpers modules in sys.modules before any test imports."""
    
    # Create stub modules
    helpers_mod = ModuleType("helpers")
    helpers_ext_mod = ModuleType("helpers.extension")
    helpers_proj_mod = ModuleType("helpers.projects")
    helpers_dj_mod = ModuleType("helpers.dirty_json")
    
    # Define Extension class stub
    class Extension:
        """Stub of helpers.extension.Extension for testing extension wrappers."""
        
        def __init__(self, agent, **kwargs):
            self.agent = agent
            self.kwargs = kwargs
        
        def execute(self, **kwargs):
            """Abstract execute method — subclasses must override."""
            raise NotImplementedError("Subclasses must implement execute()")
    
    # Define get_context_project_name function stub
    def get_context_project_name(context):
        """Stub of helpers.projects.get_context_project_name.
        
        Returns context.get_data("project") if context has get_data method,
        else falls back to context.current_project attribute.
        """
        if hasattr(context, "get_data") and callable(context.get_data):
            return context.get_data("project")
        return getattr(context, "current_project", None)
    
    # Attach to modules
    helpers_ext_mod.Extension = Extension
    helpers_proj_mod.get_context_project_name = get_context_project_name
    
    # Re-export dirtyjson.loads from the real dirtyjson package
    try:
        from dirtyjson import loads
        helpers_dj_mod.loads = loads
    except ImportError:
        # If dirtyjson is not installed, create a stub that raises on use
        def loads(*args, **kwargs):
            raise ImportError("dirtyjson not installed")
        helpers_dj_mod.loads = loads
    
    # Register all modules in sys.modules
    sys.modules["helpers"] = helpers_mod
    sys.modules["helpers.extension"] = helpers_ext_mod
    sys.modules["helpers.projects"] = helpers_proj_mod
    sys.modules["helpers.dirty_json"] = helpers_dj_mod
