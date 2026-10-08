from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolName

from server.chat_agent.tools.SQLQuery.repository import IStoreQueryRepository

import logging
import re
from decimal import Decimal
import pandas as pd
import plotly.express as px
from typing import Optional

class SQLQueryTool(AgentTool):
    ALLOWED = ("select", "with")
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
                       value_column: Optional[str] = None    # ← heatmap cell value
    ):
        cleaned = sql.strip().lower()

        # single statement only
        if ";" in cleaned[:-1]:
            raise ValueError(
                "Multiple SQL statements are not allowed"
            )

        # read-only
        if not cleaned.startswith(self.ALLOWED):
            raise ValueError(
                "Only SELECT queries are allowed"
            )

        # block dangerous keywords
        forbidden = [
            "insert",
            "update",
            "delete",
            "drop",
            "alter",
            "truncate",
            "create"
        ]

        # whole words only: a column such as created_at must not trip the check
        if re.search(r"(" + "|".join(forbidden) + r")", cleaned):
            raise ValueError(
                f"Mutation queries are forbidden: the statement contains one of {forbidden} as a keyword"
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
