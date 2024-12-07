from main import * 

import streamlit as st

#added a test comment 
def redner_UI():
    st.title("BookiBee Chat Assistant")
    st.markdown("Ask anything about your bookings, flights, or tickets!")

    if st.button("REFRESH KNOWLEDEGE BASE:"):
        initialize_vectorstore()
        

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Download and load vector store if not already loaded
    if "retriever" not in st.session_state:
        load_vector_store()



    # Display chat messages
    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Input and response handling
    if user_input := st.chat_input("Ask BookiBee..."):
        # Display the user's message immediately
        
        user_placeholder = st.chat_message("user")
        with user_placeholder:
         
                st.markdown(user_input)

        # Add user's message to session state
        st.session_state["messages"].append({"role": "user", "content": user_input})
        memory.chat_memory.add_message(HumanMessage(content=user_input))

        # Placeholder for assistant's response
        response_placeholder = st.chat_message("assistant")
        with response_placeholder:
            with st.spinner("Processing..."):
                # Get response from the agent executor
                try:
                    response = executor.invoke({"input": {"question": user_input}})
                except Exception as e:
                    response = executor.invoke({"input":f"Error *{str(e)}* was encountered while generating response for query: {user_input} ,try again "})
                response_content = response["output"]

        # Add assistant's response to session state
        st.session_state["messages"].append({"role": "assistant", "content": response_content})
        memory.chat_memory.add_message(AIMessage(content=response_content))

        # Display the assistant's response
        with response_placeholder:
            st.markdown(response_content)
   





if __name__ == "__main__":
    redner_UI()


