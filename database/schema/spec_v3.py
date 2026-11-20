"""Growth IA — PROMPT 3 schema additions (additive only).

- Licences: licence types, per-tenant allocations set by the PILOTE, per-member assignments by tenant admins.
- Visibility programmes: standard / intelligent schedulers built from an AI site + competitor audit,
  recommended actions validated by the user with a frequency.
- Tenant technical audit & roadmap.
"""
from dsl import domain, extend

# ───────────────────────── LICENCES ─────────────────────────
t = domain("B. Licences", "licensing")
t("license_types", """
code text! uniq
name text!
description text
modules json! ='[]' # module codes granted; ["*"] = every module of the tenant's plan
sort_order int! =0
is_active bool! =true
""", kind="ref", comment="Types de licence utilisateur (Complète, Marketing, Commerciale, Lecture).")
t("tenant_license_allocations", """
license_type_id uuid! -> license_types
quantity int! =0 # number of seats of this type the tenant may assign (set by the PILOTE)
note text
""", kind="conf", read="member", unique=[("tenant_id", "license_type_id")],
  comment="Licences disponibles pour un tenant, par type (déclarées par le PILOTE).")
t("member_license_assignments", """
member_id uuid! -> tenant_members cascade
license_type_id uuid! -> license_types
status text! ='active' in(active,revoked)
assigned_by uuid -> auth.users setnull
assigned_at ts! =now()
revoked_at ts
reason text
""", read="member", unique=[("tenant_id", "member_id")],
  comment="Licence attribuée à un membre (une par membre, historisée).")
extend("tenant_invitations", "license_type_code text # licence attribuée à l'acceptation")

# ───────────────────────── VISIBILITY PROGRAMMES ─────────────────────────
t = domain("V. Visibilité", "visibility")
t("visibility_profiles", """
product_id uuid -> products setnull
name text!
site_urls json! ='[]'
sector text
audience text
offer text
languages json! ='[]'
countries json! ='[]'
competitors json! ='[]' # [{name, url, source: user|ai_suggested}]
goals json! ='[]'
answers json! ='{}' # réponses à l'assistant SEO/GEO
""", comment="Profil de visibilité d'un SaaS du tenant (cible, offre, concurrents, objectifs).")
t("visibility_audits", """
profile_id uuid -> visibility_profiles cascade
audit_type text! ='site' in(site,tenant_full)
scope json! ='[]' # seo, geo, prospect
status text! ='queued' in(queued,running,succeeded,failed)
progress int! =0
step text
site_findings json! ='{}'   # observé sur le site (pages, mots-clés, technique)
competitor_findings json! ='{}' # observé chez les concurrents
ai_summary json! ='{}'      # synthèse IA (marquée générée par IA)
score int
error text
started_at ts
finished_at ts
execution_id uuid
""", kind="run", comment="Audit IA site + concurrents (constats observés vs synthèse IA séparés).")
t("visibility_recommendations", """
audit_id uuid -> visibility_audits cascade
profile_id uuid -> visibility_profiles cascade
category text! in(technical,keywords,content,geo,backlinks,social,prospect)
code text!
title text!
detail text
priority text! ='medium' in(critical,high,medium,low)
impact text
effort text
evidence json! ='{}'
apply_mode text! ='manual' in(auto_connector,generated_file,ai_content,manual)
channel text # wordpress, linkedin, medium...
status text! ='proposed' in(proposed,accepted,rejected,applied,failed,scheduled)
frequency text # once, daily, weekly, monthly
times_per_period int
applied_result json! ='{}'
applied_at ts
""", comment="Actions recommandées ; l'utilisateur valide et choisit la fréquence.")
t("visibility_generated_assets", """
audit_id uuid -> visibility_audits cascade
recommendation_id uuid -> visibility_recommendations setnull
asset_type text! in(robots_txt,sitemap_xml,sitemap_images_xml,sitemap_news_xml,json_ld,open_graph,hreflang,canonical,page_404,redirects,llms_txt,article,faq,linkedin_post)
filename text
content text!
content_type text! ='text/plain'
version_number int! =1
""", comment="Fichiers et contenus générés prêts à déployer (versionnés).")
t("tenant_roadmap_items", """
audit_id uuid -> visibility_audits setnull
phase text! ='now' in(now,next,later)
area text! in(seo,geo,ai_search,content,publishing,measurement,technical)
title text!
detail text
priority text! ='medium' in(critical,high,medium,low)
status text! ='todo' in(todo,in_progress,done,dropped)
kpi text
due_date date
""", comment="Roadmap de développement de la visibilité du tenant.")
t("ai_visibility_questions", """
profile_id uuid -> visibility_profiles cascade
question text!
intent text in(discovery,comparison,alternative,problem,brand)
language text ='fr'
source text! ='library' in(library,user,ai_suggested)
is_active bool! =true
""", comment="Bibliothèque de questions testées sur les moteurs IA.")

extend("tenant_schedulers", """
scheduler_kind text! ='standard' in(standard,intelligent)
visibility_profile_id uuid -> visibility_profiles setnull
recommendation_ids json ='[]'
""")
