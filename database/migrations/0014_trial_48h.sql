-- Growth IA - essai gratuit de 2 jours (48 h) pour tout nouvel utilisateur (plan DEMO).
-- A APPLIQUER AU MOMENT DU DEPLOIEMENT (la base est partagee avec la production).
UPDATE public.subscription_plans SET trial_duration_hours = 48, name = 'Essai gratuit (2 jours)', updated_at = now()
 WHERE code = 'DEMO';
