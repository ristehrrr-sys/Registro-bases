import streamlit as st

def cargar_estilos():
    st.markdown("""
    <style>
    /* Pega aquí TODO el CSS de tu app (lo que estaba dentro del st.markdown) */
    :root{--acc:#2FB067;--card:rgba(127,127,127,.12); /* ... etc ... */
    </style>
    """, unsafe_allow_html=True)
