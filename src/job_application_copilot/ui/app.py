"""Minimal Streamlit application entry point."""

import streamlit as st


def main() -> None:
    """Render the application scaffold."""
    st.set_page_config(page_title="Job Application Copilot")
    st.title("Job Application Copilot")
    st.info("The application scaffold is ready.")


if __name__ == "__main__":
    main()
