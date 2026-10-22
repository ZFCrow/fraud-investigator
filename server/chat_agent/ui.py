# my_cl_app.py
from datetime import datetime

import httpx
import json

import chainlit as cl


import uuid
import logging

from server.chat_agent.schemas import ChatRequest

from server.core.stream.stream_events import StreamEvent 
RAG_API_STREAM_URL = "http://localhost:8000/chat/stream"  # your actual RAG stream endpoint

import traceback


@cl.on_chat_start
async def start():


    namespace: uuid.UUID = uuid.NAMESPACE_DNS  # or any other method to generate a unique namespace 
    dt = datetime.now()  
    session_id = uuid.uuid5(namespace, dt.isoformat())  # deterministic UUID based on namespace and current time
    
    # if your backend needs a session/conversation id, create one here
    cl.user_session.set("session_id", session_id)  # or generate a UUID


# Chainlit shows starters only while the thread is empty, so on_chat_start sends no greeting.
# One per planted scenario, plus an ordinary customer, to show a clean result is reported as clean.
@cl.set_starters
async def starters() -> list[cl.Starter]:
    return [
        cl.Starter(label="Samuel Hale's latest order", message="Was there anything unusual about Samuel Hale's most recent order?"),
        cl.Starter(label="Card testing", message="Are there any sessions that look like card testing?"),
        cl.Starter(label="High refund rates", message="Which customers have an unusually high refund rate?"),
        cl.Starter(label="WELCOME50 abuse", message="Is the WELCOME50 promo code being abused?"),
        cl.Starter(label="One IP, many logins", message="Has any single IP address tried to log into many different accounts?"),
        cl.Starter(label="A normal customer", message="Is there anything suspicious about Daniel Clarke's account?"),
    ]

@cl.on_message
async def main(message: cl.Message):

    msg = cl.Message(content="")
    await msg.send()

    logging.info(f"Received message: {message.content}")
    logging.info(f"Session ID: {cl.user_session.get('session_id')}")
    
    # build the dto 
    chat_request = ChatRequest(
        user_input=message.content, 
        session_id=cl.user_session.get("session_id")
    )

    try: 
        await send_stream_request(chat_request, msg)

    except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                msg.content = f"⏳ {e.response.json().get('detail', 'Too many requests. Please try again later.')}"
                await msg.update()
            elif e.response.status_code == 501: 
                logging.error(f"RAG API returned 501 Not Implemented: {traceback.format_exc()}") 
                #await cl.Message(content="⚠️ The requested pipeline or LLM is not implemented. Please check your settings.").send() 
                msg.content = "⚠️ The requested pipeline or LLM is not implemented. Please check your settings." 
                await msg.update() 
            else:
                msg.content = f"⚠️ RAG API returned an error: {e.response.status_code} - {e.response.text}" 
                await msg.update() 

        
    except httpx.TimeoutException as e: 
        logging.error(f"Request to RAG API timed out: {traceback.format_exc()}") 

        msg.content = "⚠️ Request timed out. Please try again later." 
        await msg.update() 
    except Exception as e:
        logging.error(f"chainlit UI: {traceback.format_exc()}") 

        msg.content = f"⚠️ An unexpected error occurred: {str(e)}" 
        await msg.update() 


@cl.action_callback("follow_up")
async def on_summarize(action: cl.Action):
    logging.info(f"follow up action triggered with payload: {action.payload}")
    # Here you can implement the logic to handle the summarize trend action
  
    # Sent as the user's own message, so the chat shows the full question that was asked
    # (the button only carries its short label); main() then answers it like a typed one.
    question = cl.Message(content=action.payload.get("value", ""), type="user_message")
    await question.send()

    await main(question)

def client_id() -> str:
    """Who is asking, for the API's rate limit: the browser's IP (as forwarded by the
    reverse proxy, else the socket's), falling back to the chat session."""
    environ = cl.context.session.environ or {}
    forwarded = environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    return forwarded or environ.get("REMOTE_ADDR") or str(cl.user_session.get("session_id"))


# tool calls left out of the clickable chain: schema reads return the same text every time,
# and the follow-up questions are already shown as buttons
_UNCHAINED_TOOLS = {"get_sql_schema", "get_vector_store_schema", "get_fraud_pattern_search_schema",
                    "follow_up_question_generator"}
STEPS_PANEL = "Models & timing"
_MAX_ROWS = 20


def _output_markdown(output) -> str:
    """A tool's output, trimmed for the side panel: SQL rows as a table, search hits as text."""
    if isinstance(output, list) and output and isinstance(output[0], dict):
        cols = list(output[0].keys())
        rows = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in output[:_MAX_ROWS])
        table = f"| {' | '.join(cols)} |\n|{'---|' * len(cols)}\n{rows}"
        more = f"\n\n…and {len(output) - _MAX_ROWS} more row(s)." if len(output) > _MAX_ROWS else ""
        return f"{len(output)} row(s)\n\n{table}{more}"
    if isinstance(output, list):
        hits = "\n\n---\n\n".join(str(o)[:1500] for o in output[:5])
        more = f"\n\n…and {len(output) - 5} more." if len(output) > 5 else ""
        return f"{len(output)} result(s)\n\n{hits}{more}" if output else "No results."
    return str(output)[:3000]


def tool_panels(trace: dict) -> list[tuple[str, str]]:
    """One (name, markdown) side panel per tool call the agent actually ran, read from its
    trace -- not the answer's own Reasoning/Trace section, which the model writes and can
    misstate. Names are numbered, since the same tool can run twice (e.g. a repaired query)."""
    panels: list[tuple[str, str]] = []
    for tc in trace.get("tool_calls") or []:
        if tc["tool_name"] in _UNCHAINED_TOOLS:
            continue
        status = tc["status"] + (f" ({tc['error_type']})" if tc.get("error_type") else "")
        args: dict = tc["input_args"]
        tool_input = (f"```sql\n{args['sql']}\n```" if "sql" in args
                      else f"```json\n{json.dumps(args, indent=2)}\n```")
        name = f"{len(panels) + 1}. {tc['tool_name']}"
        panels.append((name, f"# {name}\n\nStatus: **{status}**\n\n## Input\n\n{tool_input}\n\n"
                             f"## Output\n\n{_output_markdown(tc['output'])}"))
    return panels


def steps_panel(trace: dict) -> str:
    """Which model served each workflow step and how long its LLM call took."""
    rows = "\n".join(
        f"| {s['step_name']} | {s.get('model') or '—'} | "
        + (f"{s['latency_ms'] / 1000:.1f}" if s.get("latency_ms") is not None else "—")
        + " |"
        for s in trace.get("steps") or []
    )
    return f"# {STEPS_PANEL}\n\n| Step | Model | LLM time (s) |\n|---|---|---|\n{rows}"


async def send_stream_request(chat_request, msg):

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            RAG_API_STREAM_URL,
            json=chat_request.model_dump(mode="json"),
            headers={"X-Client-Id": client_id()},
        ) as response:

            # an error response has a JSON body (e.g. the rate limiter's message), and it can
            # only be read while this stream is still open -- not later in the except block
            if response.is_error:
                await response.aread()
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line:
                    continue

                event = StreamEvent.model_validate_json(line)

                match event.event:
                    case "progress":
                        msg.content = f"⏳ {event.data}"
                        await msg.update()

                    case "error":
                        msg.content = f"❌ {event.data}"
                        await msg.update()
                    
                    case "answer": 
                        msg.content = event.data
                        await msg.update() 
                    
                    case "graph":
                        import plotly
                        fig = plotly.io.from_json(event.data)
                        #msg.elements = msg.elements or []
                        msg.elements.append(
                            cl.Plotly(
                                name="chart",
                                figure=fig,
                                display="inline"
                            )
                        )
                        await msg.update()
                    
                    case "metadata":
                        logging.info(f"msg.id={msg.id}, existing elements={[e.name for e in msg.elements]}")
                        data = dict(event.data)

                        # two payloads share this event: the agent's trace, sent with the answer
                        # (it has tool_calls), and the judge's evaluation, sent once the judge is done
                        if "tool_calls" in data:
                            panels = tool_panels(data)
                            for name, content in panels + [(STEPS_PANEL, steps_panel(data))]:
                                msg.elements.append(cl.Text(name=name, content=content, display="side"))
                            # Chainlit turns an element's name in the message text into a link
                            # that opens its side panel
                            chain = " → ".join(name for name, _ in panels) or "no tools called"
                            msg.content += f"\n\n---\n**Tools:** {chain} · {STEPS_PANEL}"
                            await msg.update()
                            continue

                        # the evaluation of this answer
                        sections = [f"# Query \n\n ## User Input: {chat_request.user_input}", "## Evaluation Results"]

                        rows = "\n".join(
                            f"| {metric} | {data[metric]['score']} | {data[metric]['reasoning']} |"
                            for metric in data.keys()
                            if isinstance(data[metric], dict)
                        )

                        sections.append(
                            "| Component | Score | Reasoning |\n"
                            "|---|---|---|\n"
                            f"{rows}"
                        )

                        sections.append(
                            f"**Overall Result:** {data.get('overall_result')}\n\n"
                            f"**Overall Reasoning:** {data.get('overall_reasoning')}"
                        )

                        # transposed (field-as-row-label) table, not header-on-top/data-below —
                        # there's only ever one record here, so a wide table with 4 column
                        # headers and a single data row underneath reads worse than one row per field.
                        tool_routing_rows = "\n".join(
                            f"| **{label}** | {value} |"
                            for label, value in [
                                ("Tool Routing Correct", data.get("tool_routing_correct")),
                                ("Tool Routing Reasoning", data.get("tool_routing_reasoning")),
                                ("Expected Tool Calls", data.get("expected_tool_calls")),
                                ("Route Efficiency", data.get("route_efficiency")),
                            ]
                        )
                        sections.append(
                            "## Tool Routing\n\n"
                            "| Metric | Value |\n"
                            "|---|---|\n"
                            f"{tool_routing_rows}"
                        )


                        # appended, so charts already on the message are kept
                        msg.elements.append(
                            cl.Text(
                                name = "Answer quality",
                                content = "\n\n---\n\n".join(sections),
                                display = "side"
                            )
                        )

                        
                        
                        logging.info(f"msg.id={msg.id}, updated elements={[e.name for e in msg.elements]}")
                        await msg.update()
                    
                    case "action":
                        data = dict(event.data)
                        # best is validate the data to a actions dto
                        # should contain 2 key (short and long)
                        actions = [
                            cl.Action(
    name="follow_up", 
    label=data.get("short"), 
    payload={"value": data.get("long")}  # <--- Move 'value' here
)
                            ]
                        # Update the message with both the graph element and the actions
                        msg.actions = actions
                        await msg.update() 


