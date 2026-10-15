from server.chat_agent.schemas import ToolCall
from server.chat_agent.tools.tool import AgentTool
from server.chat_agent.tools.enums import ToolName

SCHEMA = """
## Fraud pattern web search (Tavily)

Searches the public web -- fraud-prevention vendors, payment networks, regulators, industry
reports -- for a fraud or abuse pattern, so the answer can say whether what the store data
shows matches a known scheme, with source links.

### Arguments
- pattern_summary (str) -- the behaviour seen in the store data, rewritten generically: what
  happened, in what order, how fast, how many. No identifiers of any kind.
- query (str) -- the web search itself: the pattern in the words fraud write-ups use, plus the
  likely name of the scheme if one fits. 5-15 words.
- max_results (int) -- 3-5.

### What must NOT be sent (it leaves the system)
Customer names, emails, device ids, IP addresses, card fingerprints or last-4 digits, order,
session or address ids, exact timestamps, and the store's own amounts. A query carrying any of
these is rejected before it is sent.

### Known patterns worth naming in the query when they fit
- card testing / carding: many small or declined payments, several cards, one device or IP,
  minutes apart, often a guest checkout, sometimes one large purchase after
- account takeover: new device and country, failed logins, password reset, email or address
  change, then a large order
- refund abuse / returns fraud: repeated refunds, "item not received" claims, refund rate far
  above other customers
- promo / coupon abuse: many new accounts on one device redeeming the same first-order code
- triangulation fraud: orders shipped to many unrelated addresses, paid with different cards,
  each card's billing country unlike the shipping one
- friendly fraud / chargeback abuse: a customer disputing their own legitimate purchases

## Example
Store data: one guest device tried 9 different cards in 4 minutes, 8 declined, then one $640 order.
-> pattern_summary: "One device tries many different cards in minutes; nearly all small attempts
   decline, then a single large order is approved."
-> query: "card testing many declined cards then large purchase ecommerce fraud"
"""


class FraudPatternSearchSchemaTool(AgentTool):
    def __init__(
            self,
            tools_called: list[ToolCall] = None):

        super().__init__(ToolName.GET_FRAUD_PATTERN_SEARCH_SCHEMA, tools_called)

    async def __call__(self) -> str:
        return SCHEMA
