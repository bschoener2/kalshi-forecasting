**Goal

The overall objective is to make money by buying and selling Kalshi contracts. 
These purchases will be based on a forecast of the relevant market.

**Forecast models

We will first build the list of all Kalshi markets with sufficient historical
data (perhaps 1+ years).

We will then build a variety of time series forecasting models for these
markets. The primary approach will be to estimate the market price at noon PST
the following day. The input data will be the historical market prices for that
market.

We will build a variety of time series forecasting models for different
markets. We will identify the top model+market combinations that have the
highest predictive value. Note that during this process, we will need to be
careful to avoid any overfitting or p-hacking due to the fact that we will be
trying out many models and markets. Our evaluation of which models are
promising should take into account the number of models that we tried, and the
probability that the models have been overfitted due to chance and will
therefore underperform in future-looking predictions.

In the initial model and market selection phase, we should compute regular
model accuracy metrics and display for the user. We should also also compute
(either statically, with a heuristic, or via a basic simulation) the expected
value of the daily-decision-at-noon strategy, inclusive of Kalshi transaction
costs.

**Execution system

Once we have identified the small number of Kalshi markets to concentrate on,
we will place a buy or sell order at noon PST each day, with the intention of
holding until noon the next day. This determination of buy/sell activity will
be done by an automated program which will run shortly before noon. Then, on
the next day, the program will run again, and will determine whether to exist
the existing Kalshi positions (and buy new positions per the forecast), or hold
the existing Kalshi positions, or some combination thereof.

A human-in-the-loop flow via webserver will gate all buy/sell decisions. Before
any order execution is made, a human must click Approve in the UI for each day.
As the system proves itself, this restriction may be relaxed over time, and the
system will trade automatically (but respect an overall limit for total dollars
invested).

All orders will be written to a local log CSV file as well as a local DB for
tracking purposes.

The program will have a specific budget to play with, and must adhere to that
budget at all times. The program should use a heuristic (or more fancy model,
perhaps an optimization) to determine how much of the budget should be invested
in a given day. This should be determined by the competing goals of maximizing
long-term returns over a mult-month period, while also minimizing chances of
abruptly losing all funds due to normal or abnormal market fluctiations.

The execution system should take into account Kalshi transaction costs, and
seek to minimize them. It should also pursue a strategy with positive expected
value even when transaction costs are included.

**Web UI

A webserver will be running to show important information about which
positions are held, which are proposed for tomorrow, and metrics about overall
system performance to date. This webserver will have a human-in-the-loop
approval for all buy/sell decisions that will be made on Kalshi (though as
noted above, this restriction may be relaxed in the future).


**Tech stack

Backend language: Python
DB: local postgres
Frontend: whatever you recommend

**Agents

We will have two Claude Code agents:
 - Laptop: This claude code agent runs natively on my laptop. It is responsible
   for docker build and run scripts, managing the git log, and managing the
   running Dev docker image and docker postgres db.
 - Dev: This claude code agent runs in a docker container with
   --dangerously-skip-permissions. It will be used to build the project with
   high independence without putting the laptop at risk from security issues.

Each instance of Claude Code must know whether it is Dev or Laptop before
doing any work. Check the environment variable CLAUDE_AGENT_ROLE:
 - If CLAUDE_AGENT_ROLE=dev, you are the Dev agent.
 - If CLAUDE_AGENT_ROLE is unset or any other value, ask the user to confirm
   your role before proceeding.

These Claude Code instances will work in the same repo but will have different
.claude folders. The workspace will be mounted into the Dev docker image so
that the Dev claude can make edits.
