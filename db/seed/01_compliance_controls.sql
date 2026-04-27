--==============================================================================
-- File:        db/seed/01_compliance_controls.sql
-- Purpose:     Idempotent seed of 31 compliance controls for tenant T001
--              (DEU_BMVG) covering NIS2 (12), DORA (8), GDPR (6) and
--              VS-NfD (5) — Sovereign Defence Intelligence Platform.
-- Target:      Oracle AI Database 26ai (Autonomous Transaction Processing)
-- Depends on:  db/schema/01_tenants_and_security.sql  (tenants, DICE_POLICY
--              labels U=10, R=30, C=50, S=70)
--              db/schema/02_core_tables.sql (compliance_controls)
-- Notes:
--   * Re-runnable: deletes all T001 rows first, then re-inserts.
--   * Other tenants (T002, T003, T004) seed their own controls separately.
--   * ols_label values: 30 = R (RESTRICTED), 50 = C (CONFIDENTIAL).
--   * Descriptions cite the actual article / paragraph numbers of each
--     framework so the audit trail is human-traceable.
--==============================================================================

SET DEFINE OFF;
WHENEVER SQLERROR CONTINUE;

--------------------------------------------------------------------------------
-- 0. Wipe existing T001 controls (idempotent re-seed).
--------------------------------------------------------------------------------
DELETE FROM compliance_controls WHERE tenant_id = 'T001';

--------------------------------------------------------------------------------
-- 1. Insert 31 controls for tenant T001.
--    INSERT ALL with a single SELECT 1 FROM dual sentinel.
--    Each row uses SYS_GUID() to derive the control_id (RAW(16) semantics
--    cast into the VARCHAR2(36) PK column).
--------------------------------------------------------------------------------
INSERT ALL
  -- ============================================================================
  -- NIS2 — 12 controls (Directive (EU) 2022/2555, Annex)
  -- ============================================================================
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-01',
    'Risikomanagement-Konzept (Art. 21 Abs. 2 lit. a)',
    'Etablierung und Pflege eines dokumentierten Risikomanagement-Rahmenwerks fuer Netz- und Informationssysteme gemaess Artikel 21 Absatz 2 Buchstabe a NIS2. Risiken werden mindestens jaehrlich neu bewertet und im Vorstand abgenommen.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-02',
    'Behandlung von Sicherheitsvorfaellen (Art. 21 Abs. 2 lit. b)',
    'Prozesse zur Erkennung, Analyse, Eindaemmung und Wiederherstellung nach Sicherheitsvorfaellen gemaess Artikel 21 Absatz 2 Buchstabe b. Frueh-, Zwischen- und Abschlussbericht an die nationale CSIRT-Stelle innerhalb 24/72/30 Stunden bzw. Tagen.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-03',
    'Geschaeftskontinuitaet und Krisenmanagement (Art. 21 Abs. 2 lit. c)',
    'Aufrechterhaltung und Wiederherstellung des Betriebs nach Stoerungen gemaess Artikel 21 Absatz 2 Buchstabe c, einschliesslich Backup-Management, Disaster Recovery und Krisenmanagement. Wiederanlaufzeiten (RTO/RPO) sind je kritischem Service definiert.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-04',
    'Sicherheit der Lieferkette (Art. 21 Abs. 2 lit. d)',
    'Bewertung und Steuerung von Sicherheitsrisiken in der Lieferkette einschliesslich direkter Lieferanten und Dienstleister gemaess Artikel 21 Absatz 2 Buchstabe d. Vertraegliche Mindestanforderungen an Sicherheit, Vorfallmeldung und Audits sind festgelegt.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-05',
    'Sicherheit bei Erwerb, Entwicklung und Wartung (Art. 21 Abs. 2 lit. e)',
    'Sicherheitsmassnahmen ueber den gesamten Lebenszyklus von Netz- und Informationssystemen, inkl. Schwachstellenoffenlegung, Patch-Management und Secure-SDLC, gemaess Artikel 21 Absatz 2 Buchstabe e. Coordinated-Vulnerability-Disclosure-Programm ist veroeffentlicht.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-06',
    'Bewertung der Wirksamkeit der Massnahmen (Art. 21 Abs. 2 lit. f)',
    'Strategien und Verfahren zur Bewertung der Wirksamkeit der Risikomanagement-Massnahmen gemaess Artikel 21 Absatz 2 Buchstabe f. Interne und externe Pruefungen werden mindestens jaehrlich durchgefuehrt.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-07',
    'Cyberhygiene und Schulung (Art. 21 Abs. 2 lit. g)',
    'Grundlegende Cyberhygiene und regelmaessige Cybersicherheitsschulung des Personals gemaess Artikel 21 Absatz 2 Buchstabe g. Schulungsteilnahme wird je Mitarbeiter dokumentiert und bei Onboarding/Wiederholung nachgewiesen.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-08',
    'Kryptografie und Verschluesselung (Art. 21 Abs. 2 lit. h)',
    'Strategien und Verfahren fuer den Einsatz von Kryptografie und gegebenenfalls Verschluesselung gemaess Artikel 21 Absatz 2 Buchstabe h. Verbindliche Algorithmen, Schluesselstaerken und Schluesselrotation richten sich nach BSI TR-02102.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-09',
    'Personalsicherheit und Hintergrundpruefung (Art. 21 Abs. 2 lit. i)',
    'Personalsicherheitsmassnahmen einschliesslich Hintergrundpruefungen und Geheimhaltungsvereinbarungen gemaess Artikel 21 Absatz 2 Buchstabe i. Sicherheitsueberpruefungen nach SUeG sind fuer Rollen mit Zugriff auf VS-NfD-Material verpflichtend.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-10',
    'Zugriffs- und Asset-Management (Art. 21 Abs. 2 lit. i)',
    'Zugriffskontrollkonzepte und Asset-Management gemaess Artikel 21 Absatz 2 Buchstabe i. Inventar aller Informationsassets ist mit Klassifizierung, Eigner und Schutzbedarf in einem CMDB-Eintrag gefuehrt.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-11',
    'Multi-Faktor-Authentifizierung (Art. 21 Abs. 2 lit. j)',
    'Einsatz von Multi-Faktor-Authentifizierung oder kontinuierlicher Authentifizierung sowie gesicherten Sprach-, Video- und Textkommunikationsmitteln gemaess Artikel 21 Absatz 2 Buchstabe j. MFA ist verpflichtend fuer alle administrativen und Remote-Zugriffe.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'NIS2', 'NIS2-12',
    'Netzwerksicherheit und Segmentierung (Art. 21 Abs. 2 lit. j)',
    'Sicherung des Netzes durch Segmentierung, Firewalls und Erkennungssysteme gemaess Artikel 21 Absatz 2 Buchstabe j. Zonen-Trennung zwischen IT-, OT- und VS-Netzen wird durch dedizierte Diodenuebergaenge bzw. zugelassene Sicherheitsgateways umgesetzt.',
    'T001', 30)
  -- ============================================================================
  -- DORA — 8 controls (Regulation (EU) 2022/2554)
  -- ============================================================================
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-01',
    'IKT-Risikomanagementrahmen (Art. 6)',
    'Aufbau und Pflege eines umfassenden, dokumentierten IKT-Risikomanagementrahmens gemaess Artikel 6 DORA. Verantwortung liegt beim Leitungsorgan, Aktualisierung mindestens jaehrlich oder bei wesentlichen Aenderungen.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-02',
    'Klassifizierung von IKT-Vorfaellen (Art. 18)',
    'Klassifizierung schwerwiegender IKT-bezogener Vorfaelle nach Schwellenwerten gemaess Artikel 18 DORA und der zugehoerigen RTS. Kriterien sind Anzahl betroffener Kunden, Datenverlust, geografische Reichweite und Dauer.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-03',
    'Meldung schwerwiegender IKT-Vorfaelle (Art. 19, RTS)',
    'Meldung schwerwiegender IKT-Vorfaelle an die zustaendige Behoerde via Erst-, Zwischen- und Abschlussmeldung gemaess Artikel 19 DORA und der ITS/RTS zur Vorfallmeldung. Fristen: 4h initial, 72h Zwischenbericht, 1 Monat Abschluss.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-04',
    'Digitale operationale Resilienztests (Art. 24-26)',
    'Programm fuer regelmaessige Tests der digitalen operationalen Resilienz gemaess Artikel 24 bis 26 DORA. Mindestens jaehrliche Schwachstellenscans, Penetrationstests und Wiederanlauftests fuer kritische Systeme.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-05',
    'Threat-Led Penetration Testing (Art. 26-27)',
    'Bedrohungsorientierte Penetrationstests (TLPT) nach TIBER-EU-aehnlichem Verfahren gemaess Artikel 26 und 27 DORA. Frequenz mindestens alle drei Jahre fuer kritische oder bedeutende Funktionen, Live-Produktion mit Red-Team-Provider.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-06',
    'Risikomanagement IKT-Drittparteien (Art. 28-30)',
    'Steuerung der Risiken aus IKT-Dienstleistungen Dritter, einschliesslich Vertragsgestaltung und Exit-Strategien, gemaess Artikel 28 bis 30 DORA. Konzentrationsrisiken sind im Register kritischer Drittanbieter dokumentiert.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-07',
    'Reaktion und Wiederherstellung (Art. 11-13)',
    'Strategien, Verfahren und Plaene fuer Reaktion und Wiederherstellung gemaess Artikel 11 bis 13 DORA. Backups sind vom Produktionssystem getrennt; Wiederherstellungstests werden mindestens jaehrlich erfolgreich nachgewiesen.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'DORA', 'DORA-08',
    'Informationsaustausch zu Cyberbedrohungen (Art. 45)',
    'Vereinbarungen zum Austausch von Cyberbedrohungsinformationen mit anderen Finanzunternehmen und Behoerden gemaess Artikel 45 DORA. Teilnahme an einschlaegigen ISACs und Nutzung des STIX/TAXII-Standards sind etabliert.',
    'T001', 30)
  -- ============================================================================
  -- GDPR — 6 controls (Regulation (EU) 2016/679)
  -- ============================================================================
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'GDPR', 'GDPR-01',
    'Rechtmaessigkeit der Verarbeitung (Art. 6)',
    'Sicherstellung einer gueltigen Rechtsgrundlage fuer jede Verarbeitung personenbezogener Daten gemaess Artikel 6 DSGVO. Die Rechtsgrundlage ist je Verarbeitungstaetigkeit im Verzeichnis nach Artikel 30 dokumentiert.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'GDPR', 'GDPR-02',
    'Rechte der betroffenen Person (Art. 12-22)',
    'Verfahren zur Bearbeitung der Rechte betroffener Personen — Auskunft, Berichtigung, Loeschung, Einschraenkung, Datenuebertragbarkeit, Widerspruch — gemaess Artikel 12 bis 22 DSGVO. Antworten erfolgen innerhalb eines Monats.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'GDPR', 'GDPR-03',
    'Datenschutz-Folgenabschaetzung (Art. 35)',
    'Durchfuehrung einer Datenschutz-Folgenabschaetzung (DPIA) bei voraussichtlich hohem Risiko fuer die Rechte und Freiheiten natuerlicher Personen gemaess Artikel 35 DSGVO. Konsultation der Aufsichtsbehoerde nach Artikel 36 bei Restrisiko.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'GDPR', 'GDPR-04',
    'Meldung von Datenschutzverletzungen (Art. 33-34)',
    'Meldung von Verletzungen des Schutzes personenbezogener Daten an die Aufsichtsbehoerde innerhalb von 72 Stunden gemaess Artikel 33 DSGVO sowie Benachrichtigung der Betroffenen bei hohem Risiko gemaess Artikel 34 DSGVO.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'GDPR', 'GDPR-05',
    'Verzeichnis der Verarbeitungstaetigkeiten (Art. 30)',
    'Pflege eines Verzeichnisses aller Verarbeitungstaetigkeiten als Verantwortlicher und als Auftragsverarbeiter gemaess Artikel 30 DSGVO. Das Verzeichnis wird zentral gepflegt und auf Anfrage der Aufsichtsbehoerde vorgelegt.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'GDPR', 'GDPR-06',
    'Benennung des Datenschutzbeauftragten (Art. 37)',
    'Benennung eines Datenschutzbeauftragten gemaess Artikel 37 DSGVO und Veroeffentlichung der Kontaktdaten gegenueber der Aufsichtsbehoerde und den Betroffenen. Unabhaengigkeit und Ressourcen sind nach Artikel 38 sichergestellt.',
    'T001', 30)
  -- ============================================================================
  -- VS-NfD — 5 controls (Allgemeine Verwaltungsvorschrift VSA des BMI)
  -- ============================================================================
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'VSNFD', 'VSNFD-01',
    'Physische Handhabung von VS-NfD (VSA Anlage III Nr. 2)',
    'Physische Handhabung von Verschlusssachen des Geheimhaltungsgrades VS-NfD gemaess VSA Anlage III Nummer 2. Die Aufbewahrung erfolgt in verschliessbaren Behaeltnissen ausserhalb der Dienstzeit, Mitfuehren ausserhalb der Dienststelle nur mit Einzelgenehmigung.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'VSNFD', 'VSNFD-02',
    'Aufbewahrung eingestufter Daten (VSA Anlage III Nr. 2.3)',
    'Anforderungen an die Aufbewahrung von VS-NfD-Material auf IT-Systemen gemaess VSA Anlage III Nummer 2.3. Speicherung nur auf Systemen mit BSI-Zulassung fuer VS-NfD oder gleichwertiger Zulassung; Wechseldatentraeger sind zu kennzeichnen und zu inventarisieren.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'VSNFD', 'VSNFD-03',
    'Uebermittlung und Transport (VSA Anlage III Nr. 3)',
    'Vorschriften zur Uebermittlung und zum Transport von VS-NfD gemaess VSA Anlage III Nummer 3. Elektronische Uebertragung nur mit BSI-zugelassenen Verschluesselungsverfahren (z. B. SINA), Postversand in doppeltem Umschlag mit innerem VS-NfD-Aufdruck.',
    'T001', 50)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'VSNFD', 'VSNFD-04',
    'Kennzeichnung und Markierung (VSA Anlage III Nr. 1)',
    'Vorgaben fuer die Kennzeichnung und Markierung von VS-NfD-Dokumenten und -Datentraegern gemaess VSA Anlage III Nummer 1. Jede Seite traegt die Markierung VS-Nur fuer den Dienstgebrauch oben und unten; elektronische Dateien tragen die Markierung in Header und Metadaten.',
    'T001', 30)
  INTO compliance_controls (control_id, framework, code, title, description, tenant_id, ols_label) VALUES (
    SYS_GUID(), 'VSNFD', 'VSNFD-05',
    'Vernichtung und Aussonderung (VSA Anlage III Nr. 4)',
    'Verfahren zur Vernichtung und Aussonderung von VS-NfD-Material gemaess VSA Anlage III Nummer 4. Papier wird mit Aktenvernichtern der Sicherheitsstufe P-4 oder hoeher zerkleinert; Datentraeger werden nach BSI TL 03420 sicher geloescht oder physisch zerstoert.',
    'T001', 50)
SELECT 1 FROM dual;

COMMIT;

--==============================================================================
-- Verify count after seed (informational; does not affect transaction).
--==============================================================================
SET SERVEROUTPUT ON SIZE UNLIMITED
DECLARE
  v_total   PLS_INTEGER;
  v_nis2    PLS_INTEGER;
  v_dora    PLS_INTEGER;
  v_gdpr    PLS_INTEGER;
  v_vsnfd   PLS_INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_total FROM compliance_controls WHERE tenant_id = 'T001';
  SELECT COUNT(*) INTO v_nis2  FROM compliance_controls WHERE tenant_id = 'T001' AND framework = 'NIS2';
  SELECT COUNT(*) INTO v_dora  FROM compliance_controls WHERE tenant_id = 'T001' AND framework = 'DORA';
  SELECT COUNT(*) INTO v_gdpr  FROM compliance_controls WHERE tenant_id = 'T001' AND framework = 'GDPR';
  SELECT COUNT(*) INTO v_vsnfd FROM compliance_controls WHERE tenant_id = 'T001' AND framework = 'VSNFD';
  DBMS_OUTPUT.PUT_LINE('Seed complete: T001 total='||v_total||
                       ' NIS2='||v_nis2||' DORA='||v_dora||
                       ' GDPR='||v_gdpr||' VSNFD='||v_vsnfd);
END;
/

--==============================================================================
-- End of 01_compliance_controls.sql
--==============================================================================
