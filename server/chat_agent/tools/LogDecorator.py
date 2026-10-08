import functools
import json
from server.chat_agent.schemas import ToolCall

# suppose to log the results of all the tools 
# convert the output to str so that the agent can read it properly!
import logging

def log_tool_call(tool_name: str, 
                  tools_called: list[ToolCall]):
    
    def decorator(func):
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # log it before 
            logging.info(f"calling Tool {tool_name}  with args {kwargs}") 
            
            # call the actual tool
            output = None
            try:
                output = await func(*args, **kwargs)
                output_str : str = "" 
                # convert to str here 
                if isinstance(output, list):
                    if output:
                        output_str = "\n\n---\n\n".join(
                            item if isinstance(item, str) else json.dumps(item, default=str) 
                            for item in output
                        )
                    else:
                        output_str = "No results found."
                
                elif isinstance(output, dict):
                    output_str = json.dumps(output, default=str)
                else: 
                    output_str = str(output) 


                #logging.info(f"Tool {tool_name} final output type {type(output)}, output : {output}")  
                return output_str
            
            except Exception as e:
                logging.error(f"Error occurred while calling Tool {tool_name}: {e}")
                # assigned to output (not just returned) so the ToolCall logged in the
                # finally clause carries the error instead of failing validation on None
                output = f"ERROR: {e}"
                return output
            
            finally:
                # log it after
                tools_called.append(
                    ToolCall(
                        tool_name=tool_name,
                        input_args=kwargs,  # kwargs captures all named args
                        output=output
                    )
                )

                logging.info(f"Tool {tool_name} called with args {kwargs} and returned output: {output}")
                

        
        return wrapper
    
    return decorator