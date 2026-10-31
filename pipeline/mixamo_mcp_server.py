import sys
import json
import os
import subprocess
from pathlib import Path
from mixamo_state import character_name, read_state, write_state, state_path

SESSION_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.local/auth/mixamo_session.json"))
PYTHON_BIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.local/python/bin/python3"))
CONTROLLER_SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), "mixamo_controller.py"))

def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mixamo-automator", "version": "2.0.0"}
            }
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "mixamo_check_login",
                        "description": "Check whether a local session file exists; this does not verify server validity.",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "mixamo_upload_and_rig",
                        "description": "Start visible human-assisted rigging. Returns immediately; the user places markers and confirms the preview. Poll mixamo_rig_status for readiness.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Path to character zip or obj"},
                                "character": {"type": "string", "description": "Workspace character ID"}
                            },
                            "required": ["file_path", "character"]
                        }
                    },
                    {
                        "name": "mixamo_rig_status",
                        "description": "Read human-assisted rigging status. Only ready permits animation downloads.",
                        "inputSchema": {"type": "object", "properties": {"character": {"type": "string"}}, "required": ["character"]}
                    },
                    {
                        "name": "mixamo_download_animation",
                        "description": "Search Mixamo library and download an animation as FBX.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "character": {"type": "string", "description": "Previously reviewed workspace character ID"},
                                "animation_name": {"type": "string", "description": "Exact name of animation (e.g. Running, Idle, Slash)"},
                                "output_path": {"type": "string", "description": "Source FBX path under workspaces/<character>/animations/<batch>/; never deliverables. Register the batch before baking."}
                            },
                            "required": ["character", "animation_name", "output_path"]
                        }
                    }
                ]
            }
        }
    elif method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "mixamo_check_login":
            has_session = os.path.exists(SESSION_FILE)
            msg = "Local session file found; server validity is not checked." if has_session else "No session found. Please run ./pipeline/mixamo.sh login first."
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps({"logged_in": has_session, "message": msg})}]}
            }
        elif tool_name == "mixamo_upload_and_rig":
            character = character_name(args["character"])
            fp = str(Path(args["file_path"]).resolve())
            previous = read_state(character)
            if previous.get('status') in ('launching', 'opening_browser', 'waiting_for_markers', 'processing_rig', 'waiting_for_review', 'verifying_bound_model'):
                raise ValueError("This character already has an active rigging handoff")
            if not Path(fp).is_file():
                raise ValueError("Model does not exist")
            write_state(character, "launching", source_model=fp)
            log_path = state_path(character).parent / 'handoff.log'
            with log_path.open('w') as log:
                process = subprocess.Popen([PYTHON_BIN, "-u", CONTROLLER_SCRIPT, "upload", fp,
                                            "--character", character], stdout=log, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, start_new_session=True)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps({
                "status": "launching", "pid": process.pid, "character": character,
                "log": str(log_path), "message": "Place markers in the visible browser and use the Studio confirmation button after reviewing the rig. Poll mixamo_rig_status; this is not binding success."
            })}]}}
        elif tool_name == "mixamo_rig_status":
            state = read_state(character_name(args["character"]))
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(state)}]}}
        elif tool_name == "mixamo_download_animation":
            anim = args.get("animation_name")
            out = args.get("output_path")
            res = subprocess.run([PYTHON_BIN, CONTROLLER_SCRIPT, "download", anim, out, "--character", character_name(args["character"])], capture_output=True, text=True)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"isError": res.returncode != 0, "content": [{"type": "text", "text": res.stdout + ("\nError: " + res.stderr if res.returncode != 0 else "")}]}
            }
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
    elif method == "notifications/initialized":
        return None
    else:
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except Exception as e:
            err = {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
