import streamlit as st

price = st.slider('Price change %', -20, 20, 0)
base = st.number_input('Baseline units', 1000)
st.metric('Projected units', int(base * (1 - 0.012 * price)))
