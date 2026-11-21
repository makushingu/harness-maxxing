"""`maxxing topics …`: the projects and topics of the workspace.

  maxxing topics list [--json]                         every project and topic with its description
  maxxing topics new PROJECT/TOPIC [--description D] [--project-description D]
                                                       a topic (and its project when it is new)
"""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="topics_cmd", required=True)
    ls = sub.add_parser("list", help="every project and topic with its description")
    ls.add_argument("--json", action="store_true")
    n = sub.add_parser("new", help="a topic (and its project when it is new)")
    n.add_argument("topic", help="<project>/<topic> (lowercase letters, digits, -)")
    n.add_argument("--description", default="", help="what the topic is for (first paragraph of its CLAUDE.md)")
    n.add_argument("--project-description", default="", help="the project's, when it is created")


def _handler(a) -> int:
    from . import workspace
    if a.topics_cmd == "list":
        tree = workspace.tree()["projects"]
        if a.json:
            print(json.dumps([{"project": p["name"], "description": p["description"],
                               "topics": [{"name": t["name"], "path": t["path"], "description": t["description"]}
                                          for t in p["topics"]]} for p in tree], indent=2))
            return 0
        for p in tree:
            print(f"{p['name']}: {p['description']}")
            for t in p["topics"]:
                print(f"  {p['name']}/{t['name']}: {t['description']}")
        return 0
    parts = a.topic.strip().strip("/").split("/")
    if parts[0] == "projects" and len(parts) == 4 and parts[2] == "topics":
        parts = [parts[1], parts[3]]
    if len(parts) != 2:
        print("PROJECT/TOPIC, e.g. acme/blog", file=sys.stderr)
        return 2
    project, topic = parts
    try:
        if not workspace.project_dir(project).is_dir():
            workspace.create_project(project, a.project_description)
            print(f"project {project} created")
        t = workspace.create_topic(project, topic, a.description)
    except workspace.WorkspaceError as e:
        print(e.message, file=sys.stderr)
        return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"topic {t['path']} created")
    return 0


cli.register("topics", "projects and topics: list them, create one (new)", _configure, _handler)
