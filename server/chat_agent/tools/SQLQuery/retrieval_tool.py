from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolName

from server.chat_agent.tools.SQLQuery.repository import IStoreQueryRepository

from server.chat_agent.tools.enums import ToolErrorType
from server.chat_agent.tools.exceptions import ToolError

import logging
import re
from decimal import Decimal
import pandas as pd
import plotly.express as px
from typing import Optional

# Postgres's ways of reading the real clock
_REAL_CLOCK = re.compile(
    r"\b(now|clock_timestamp|statement_timestamp|transaction_timestamp)\s*\("
    r"|\b(current_timestamp|current_date|current_time|localtimestamp|localtime)\b",
    re.IGNORECASE,
)


def _sgt_date(as_of: str) -> str:
    return f"TIMESTAMPTZ '{as_of}' AT TIME ZONE 'Asia/Singapore'"


class SQLQueryTool(AgentTool):
    def __init__(
            self,
            repo: IStoreQueryRepository,
            tools_called: list[ToolCall] = None,
            charts_to_send: list[str] = None  # ← add this
                 ):
        super().__init__(ToolName.QUERY_SQL,
                         tools_called)
        self.repo = repo
        self.charts_to_send: list[str] = charts_to_send
    
    async def __call__(self,
                       sql: str,
                       generate_chart: bool = False,
                       chart_type: str = "bar",
                       x_column: Optional[str] = None,  # ← agent specifies
                       y_column: Optional[str] = None,  # ← agent specifies
                       value_column: Optional[str] = None,    # ← heatmap cell value
                       # the store data's end as a timestamptz literal, e.g. "2026-10-07 09:19:52+08";
                       # set by the workflow, never by the model
                       as_of: Optional[str] = None,
    ):
        # no permission checks on the SQL text here: the repository runs it as a database user
        # that can only read the store tables, so a write is refused by Postgres itself.
        # The one text check is the clock: the data is a snapshot, so the database's own
        # "now" puts every relative window past the end of the data.
        if as_of and _REAL_CLOCK.search(sql):
            raise ToolError(
                f"The query uses the database clock (now(), current_timestamp, current_date...), "
                f"which returns today's real date, after the store data ends. Replace it with the "
                f"literal TIMESTAMPTZ '{as_of}' (or ({_sgt_date(as_of)})::date for the SGT date).",
                error_type=ToolErrorType.INVALID_QUERY,
            )
        results = await self.repo.execute_sql(sql)

        if generate_chart and results and self.charts_to_send is not None:
            
            df = pd.DataFrame(results) 
            # numeric(10,2) columns arrive as Decimal objects; plotly needs real numbers
            for column in df.columns:
                if df[column].map(lambda v: isinstance(v, Decimal)).any():
                    df[column] = df[column].astype(float)
            # use agent-specified columns or fall back to first two
            x = x_column if x_column and x_column in df.columns else df.columns[0]
            y = y_column if y_column and y_column in df.columns else df.columns[1]
            
            logging.info (df)

            fig = None
            if chart_type == "heatmap" and len(df.columns) >= 3:
                value_col = value_column if value_column and value_column in df.columns else df.columns[2]
                pivot = df.pivot_table(index=y, columns=x, values=value_col, aggfunc="sum", fill_value=0)
                fig = px.imshow(pivot, text_auto=True, aspect="auto", color_continuous_scale="Reds")

            elif len(df.columns) >= 2:
                if chart_type == "line":
                    fig = px.line(df, x=x, y=y)
                elif chart_type == "pie":
                    fig = px.pie(df, names=x, values=y)
                else:
                    fig = px.bar(df, x=x, y=y)  # default to bar (also covers unknown chart_type)

            if fig is not None:
                self.charts_to_send.append(fig.to_json())
                logging.info(f"[SQLQueryTool] Chart generated and added to charts_to_send. Total charts: {len(self.charts_to_send)}")
        return results
