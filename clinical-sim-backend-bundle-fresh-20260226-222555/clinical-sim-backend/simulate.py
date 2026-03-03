import httpx
import random
import time
import asyncio

BASE_URL = "http://127.0.0.1:8000"

AGENT_INPUTS = [
    "I will check the patient's blood pressure and heart rate.",
    "Order a CBC and BMP.",
    "Start an IV of labetalol 20mg.",
    "What is the patient's current Glasgow Coma Scale?",
    "Administer nicardipine drip at 5mg/hr.",
    "Order a non-contrast CT of the head.",
    "Call neurology for a consult.",
    "Give the patient 1g of acetaminophen.",
    "Check pupillary response.",
    "What are the patient's current symptoms?",
    "Give 10mg IV labetalol push.",
    "Recheck BP in 15 minutes.",
    "Ask the patient if they have a headache or visual changes.",
    "Order an MRI of the brain.",
    "What's the patient's medical history?",
    "Get a 12-lead ECG.",
]

async def run_agent(agent_id, num_turns=5):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Create session
        print(f"[{agent_id}] Creating session...")
        res = await client.post("/sessions", json={
            "userId": agent_id,
            "siteId": "sim",
            "deviceMode": "local_server",
            "metadata": {"simulation": True}
        })
        if res.status_code != 201:
            print(f"[{agent_id}] Failed to create session: {res.text}")
            return
        
        session_id = res.json()["sessionId"]
        
        # 2. Start case
        print(f"[{agent_id}] Starting case for session {session_id}...")
        res = await client.post(f"/sessions/{session_id}/start-case", json={
            "caseId": "htn_enceph_001"
        })
        if res.status_code != 200:
            print(f"[{agent_id}] Failed to start case: {res.text}")
            return
        
        # 3. Take turns
        for i in range(num_turns):
            input_text = random.choice(AGENT_INPUTS)
            print(f"[{agent_id}] Turn {i+1}: Sending '{input_text}'")
            res = await client.post(f"/sessions/{session_id}/turns", json={
                "inputText": input_text,
                "parserMode": "rule"  # Use rule so we don't depend on LLM config if not set
            })
            if res.status_code != 200:
                print(f"[{agent_id}] Error on turn {i+1}: {res.text}")
            else:
                data = res.json()
                print(f"[{agent_id}] Turn {i+1} completed successfully.")
            
            await asyncio.sleep(0.5)

async def main():
    print("Starting agents simulation...")
    # Run 10 agents concurrently
    agents = [run_agent(f"agent-{i}", num_turns=random.randint(4, 7)) for i in range(1, 15)]
    await asyncio.gather(*agents)
    print("Simulation complete! Data should be collected in the backend.")

if __name__ == "__main__":
    asyncio.run(main())
