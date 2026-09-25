"""Ordinary sentences said with the developer key must stay sentences."""
import sys
sys.path.insert(0, r"C:\Users\sumit\Projects\Talkative")
from talkative import dev_mode

SENTENCES = [
    "Select the best option and send it to me.",
    "Update the team on the launch plan.",
    "Set up a meeting for Monday.",
    "For now, let's ship it as it is.",
    "If you have time, review my changes.",
    "Return the laptop to IT by Friday.",
    "Get me the latest numbers please.",
    "List all the open issues in the doc.",
    "Test it on your machine first.",
    "Start the demo at three.",
    "Use the staging server for this.",
    "Create a new ticket for the login bug.",
    "Drop me a line when it's done.",
    "Delete the old branch after merging.",
    "Import the contacts from the spreadsheet.",
    "Print two copies of the report.",
    "Class starts at nine tomorrow.",
    "Count me in for the offsite.",
    "Sort out the billing issue with finance.",
    "Where did we put the design files?",
    "Data from last week looks better.",
    "User feedback has been mostly positive.",
    "Total cost came to about five thousand.",
    "Result of the test was a pass.",
    "Code review is scheduled for Thursday.",
    "While you're at it, fix the typo.",
    "With the new build, it's much faster.",
    "From what I can tell, it works.",
    "Try restarting the app first.",
    "Else we'll push it to next week.",
    "New users need to verify their email.",
    "Remove the extra slide from the deck.",
    "Stop the recording when you're done.",
    "Begin with the summary slide.",
    "Commit to a date and tell the client.",
    "I washed the dish and left.",
    "Send it to Rahul and Priya.",
    "The meeting is at noon, not at one.",
    "I think the star of the show was the demo.",
    "We need a plus one for the dinner.",
    "Get status updates from the team every Friday.",
    "Get commit access from the admin before you start.",
    "Get merge approval from two reviewers first.",
    "Get log files from the support team.",
    "Use the main branch for the release notes.",
    "Ping me when the build is green.",
    "Code it the way we discussed yesterday.",
    "Print it on both sides of the page please.",
]

bad = [(s, dev_mode.process(s)[0]) for s in SENTENCES if dev_mode.process(s)[1]]
print(f"{len(SENTENCES) - len(bad)}/{len(SENTENCES)} ordinary sentences stayed prose")
for s, out in bad:
    print(f"  CODE?  {s!r} -> {out!r}")
