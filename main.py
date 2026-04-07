    # ==================================================
    # 11) FIRMA ELETTRONICA SEMPLICE (SES/FES) – DEMO / TEST
    #     ✅ st.form → niente reload mentre scrivi
    # ==================================================
    if ENABLE_SES:
        st.divider()
        st.subheader("✍️ Firma elettronica semplice (OTP)")

        # ✅ recupera SEMPRE il passport pubblicato dallo state
        pp = st.session_state.get("published_passport")

        if not pp:
            st.info("Pubblica prima il DPP per poter avviare la firma.")
            st.stop()

        # ✅ inizializza stato UNA SOLA VOLTA
        st.session_state.setdefault("ses_name", "Mario")
        st.session_state.setdefault("ses_surname", "Rossi")
        st.session_state.setdefault("ses_email", "mario.rossi@test.it")
        st.session_state.setdefault("ses_mobile", "+39333111222")
        st.session_state.setdefault("ses_channel", "email")
        st.session_state.setdefault("ses_mode", "typed")
        st.session_state.setdefault("ses_allow_edit", False)

        # ✅ FORM (evita rerun fastidiosi)
        with st.form("ses_form", clear_on_submit=False):
            col1, col2 = st.columns(2)

            with col1:
                st.text_input("Nome firmatario (persona fisica)", key="ses_name")
                st.text_input("Cognome firmatario", key="ses_surname")
                st.text_input("Email OTP", key="ses_email")

            with col2:
                st.text_input("Cellulare OTP", key="ses_mobile")
                st.selectbox("Canale OTP", ["email", "sms"], key="ses_channel")
                st.selectbox("Modalità firma", ["typed", "drawn"], key="ses_mode")

            st.checkbox(
                "Consenti al firmatario di modificare nome/email/cellulare",
                key="ses_allow_edit"
            )

            submit_ses = st.form_submit_button("Invia richiesta firma SES")

        # ✅ CHIAMATA SES SOLO AL SUBMIT
        if submit_ses:
            with st.spinner("Invio richiesta di firma SES..."):
                try:
                    services.sign_passport_pdf_ses_openapi(
                        pp,  # ✅ SOLO pp, MAI passport
                        signer_name=st.session_state["ses_name"],
                        signer_surname=st.session_state["ses_surname"],
                        signer_email=st.session_state["ses_email"],
                        signer_mobile=st.session_state["ses_mobile"],
                        otp_channel=st.session_state["ses_channel"],
                        signature_mode=st.session_state["ses_mode"],
                        allow_user_edit=st.session_state["ses_allow_edit"]
                    )

                    services.espr_stamp(
                        pp,
                        actor="manufacturer",
                        action="request_ses_signature",
                        reason="Requested SES (OTP) signature for demo/test"
                    )

                    services.save_passport_to_file(pp)
                    services.save_passport_to_excel_append(pp)

                    # ✅ aggiorna lo state
                    st.session_state["published_passport"] = pp

                    st.success("✅ Richiesta SES inviata")
                except Exception as e:
                    st.error(f"❌ Errore SES: {e}")
                    st.stop()

        # ✅ MOSTRA LINK DI FIRMA (se presenti)
        signing_urls = (pp.get("simple_signature") or {}).get("signing_urls") or []
        signing_urls = [u for u in signing_urls if u]

        if signing_urls:
            st.markdown("### 🔗 Link firma")
            for u in signing_urls:
                st.write(u)
        elif pp.get("simple_signature"):
            with st.expander("Debug risposta SES"):
                st.json(pp["simple_signature"].get("raw_response", {}))
