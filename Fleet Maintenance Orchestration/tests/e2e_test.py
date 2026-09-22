"""
End-to-end teszt a Coffee Fleet Maintenance folyamathoz.

Elindít egy process instance-t, majd a Camunda 8 v2 REST API-n keresztül
automatikusan hozzárendeli és lezárja a nyitott user taskokat is - így
nem kell kézzel kattingatni a Tasklist-ben minden egyes teszt-futtatáskor.

Feltételek:
- api_mock/app.py fut (localhost:5000)
- camunda_worker.py fut (a service/send task-okhoz)
- Camunda 8 Run fut, REST API elérhető: localhost:8080
- a process deployolva van "Process_1a8dlsy" azonosítóval
"""

import time
import httpx

REST_BASE = "http://localhost:8080/v2"
PROCESS_DEFINITION_ID = "Process_1a8dlsy"

# elementId -> milyen változókat adjunk meg lezáráskor
# a General cleaning tasknál itt állítjuk be az issue_solved-ot
TASK_VARIABLES = {
    "Activity_0yll9sv": lambda ctx: {"issue_solved": ctx["issue_solved"]},
}

POLL_INTERVAL_SEC = 2
MAX_ITERATIONS = 60  # ~2 perc timeout


def start_instance(client: httpx.Client, alert_type: str) -> str:
    resp = client.post(
        f"{REST_BASE}/process-instances",
        json={
            "processDefinitionId": PROCESS_DEFINITION_ID,
            "variables": {"alert_type": alert_type},
        },
    )
    resp.raise_for_status()
    data = resp.json()
    key = data["processInstanceKey"]
    print(f"  Instance elindítva: {key} (alert_type={alert_type})")
    return key


def get_instance_state(client: httpx.Client, process_instance_key: str, retries: int = 5) -> str:
    """A process-instances GET endpoint 'eventually consistent' - egy frissen
    indított instance rövid ideig 404-et adhat, amíg az index frissül."""
    last_error = None
    for attempt in range(retries):
        resp = client.get(f"{REST_BASE}/process-instances/{process_instance_key}")
        if resp.status_code == 200:
            return resp.json().get("state", "UNKNOWN")
        if resp.status_code == 404:
            last_error = resp
            time.sleep(1)
            continue
        resp.raise_for_status()
    if last_error is not None:
        # instance még biztos nem tűnt el, csak nincs kiindexelve - vegyük aktívnak
        print("  [figyelem] process instance még nem indexelt (404), ACTIVE-ként kezelve")
        return "ACTIVE"
    return "UNKNOWN"


def get_open_tasks(client: httpx.Client, process_instance_key: str) -> list:
    resp = client.post(
        f"{REST_BASE}/user-tasks/search",
        json={
            "filter": {
                "processInstanceKey": process_instance_key,
                "state": "CREATED",
            }
        },
    )
    if resp.status_code != 200:
        print(f"  [figyelem] user-tasks/search hiba ({resp.status_code}): {resp.text[:200]}")
        return []
    return resp.json().get("items", [])


def assign_and_complete(client: httpx.Client, task: dict, ctx: dict):
    task_key = task["userTaskKey"]
    element_id = task.get("elementId", "")

    # hozzárendelés (ha már assigned, ezt figyelmen kívül hagyjuk)
    assign_resp = client.post(
        f"{REST_BASE}/user-tasks/{task_key}/assignment",
        json={"assignee": "e2e-test", "allowOverride": True},
    )
    if assign_resp.status_code not in (204, 409):
        print(f"  [figyelem] assign hiba ({assign_resp.status_code}): {assign_resp.text[:200]}")

    variables = {}
    if element_id in TASK_VARIABLES:
        variables = TASK_VARIABLES[element_id](ctx)

    complete_resp = client.post(
        f"{REST_BASE}/user-tasks/{task_key}/completion",
        json={"variables": variables},
    )
    if complete_resp.status_code == 204:
        print(f"  Lezárva: {element_id} (variables={variables or '-'})")
    else:
        print(f"  [hiba] completion ({complete_resp.status_code}): {complete_resp.text[:200]}")


def run_scenario(client: httpx.Client, alert_type: str, issue_solved: str):
    print(f"\n=== Szcenárió: alert_type={alert_type}, issue_solved={issue_solved} ===")
    ctx = {"issue_solved": issue_solved}
    instance_key = start_instance(client, alert_type)

    seen_tasks = set()
    for i in range(MAX_ITERATIONS):
        state = get_instance_state(client, instance_key)
        if state in ("COMPLETED", "TERMINATED", "CANCELED"):
            print(f"  Instance állapota: {state}")
            break

        tasks = get_open_tasks(client, instance_key)
        for task in tasks:
            task_key = task["userTaskKey"]
            if task_key in seen_tasks:
                continue
            seen_tasks.add(task_key)
            assign_and_complete(client, task, ctx)

        time.sleep(POLL_INTERVAL_SEC)
    else:
        print("  [figyelem] timeout - az instance nem zárult le a megadott időn belül")
        return

    final_state = get_instance_state(client, instance_key)
    print(f"  Végállapot: {final_state}")


def main():
    print(f"REST_BASE = {REST_BASE}")
    with httpx.Client(timeout=10.0) as client:
        # 1. Material ág, megoldva
        run_scenario(client, alert_type="material", issue_solved="true")

        # 2. Material ág, nem oldódott meg
        run_scenario(client, alert_type="material", issue_solved="false")

        # 3. Machine breakdown ág, megoldva
        run_scenario(client, alert_type="machine_breakdown", issue_solved="true")


if __name__ == "__main__":
    main()
