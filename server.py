"""Entry point for the web app:  streamlit run server.py

app.py is the actual website. This file mounts the large-video upload route (studio/bigupload.py) next to it,
which streams files straight to disk (2-hour / multi-GB videos without filling RAM).
`streamlit run app.py` also works, but then uploads use Streamlit's built-in uploader (up to 4 GB, held in RAM)."""
import os

import streamlit as st

from studio.bigupload import routes

os.environ["BIG_UPLOAD"] = "1"          # tell app.py that the large-file upload route is available
app = st.App("app.py", routes=routes())
