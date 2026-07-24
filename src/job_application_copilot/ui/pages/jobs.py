"""Jobs page."""

import streamlit as st

from job_application_copilot.ui.job_form import SAVED_MESSAGE_KEY

st.title("Jobs")
if saved_message := st.session_state.pop(SAVED_MESSAGE_KEY, None):
    st.success(saved_message)

st.page_link("pages/add_job.py", label="Add job")
st.info("The jobs dashboard table will be implemented in T2.5.")
