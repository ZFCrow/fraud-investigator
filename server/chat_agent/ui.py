# my_cl_app.py
from datetime import datetime

import httpx

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

    await cl.Message(content="👋 Ask me about customers, sessions, orders, payments or refunds.").send()

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
            # 1. Read the stream into memory first
            await e.response.aread()
            
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
  
    # 1. Create a "fake" message object
    # You don't need to 'await msg.send()' here because your 
    # 'main' function handles the sending of the message.
    fake_message = cl.Message(content=action.payload.get("value", ""))
    
    # 2. Call main directly
    await main(fake_message)

def client_id() -> str:
    """Who is asking, for the API's rate limit: the browser's IP (as forwarded by the
    reverse proxy, else the socket's), falling back to the chat session."""
    environ = cl.context.session.environ or {}
    forwarded = environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
    return forwarded or environ.get("REMOTE_ADDR") or str(cl.user_session.get("session_id"))


async def send_stream_request(chat_request, msg):

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            RAG_API_STREAM_URL,
            json=chat_request.model_dump(mode="json"),
            headers={"X-Client-Id": client_id()},
        ) as response:

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
                        # the evaluation of this answer, sent once the judge is done
                        data = dict(event.data)
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
                                name = f"Metadata",
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


