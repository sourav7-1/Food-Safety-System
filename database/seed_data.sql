-- Seed data imported from:
-- Street Food Stall Registration Form .csv.zip
-- The source contains 21 real form responses. No synthetic users, stalls,
-- inspections, complaints, reviews, or corrective actions are inserted.

USE smart_street_food_safety;

SET NAMES utf8mb4;
START TRANSACTION;

-- Remove the previously generated development dataset in FK-safe order.
DELETE FROM corrective_actions;
DELETE FROM reviews;
DELETE FROM complaints;
DELETE FROM complaint_types;
DELETE FROM inspection_scores;
DELETE FROM inspections;
DELETE FROM inspection_criteria;
DELETE FROM food_items;
DELETE FROM food_categories;
DELETE FROM inspectors;
DELETE FROM stalls;
DELETE FROM areas;
DELETE FROM vendors;
DELETE FROM users;
DELETE FROM roles;
DELETE FROM street_food_stall_registrations;

-- Required authorization lookup values. Public registration uses customer;
-- privileged accounts must be provisioned by an administrator.
INSERT INTO roles (role_id, role_name, description) VALUES
  (1, 'admin', 'System administrators'),
  (2, 'vendor', 'Registered street-food stall operators'),
  (3, 'inspector', 'Authorised food-safety inspectors'),
  (4, 'customer', 'Public users of the food-safety platform');

INSERT INTO street_food_stall_registrations (
  registration_id, submitted_at, vendor_name, phone_number, stall_name, area,
  full_address, food_category, food_items, average_price_bdt, food_covered,
  clean_water_used, waste_bin_available, vendor_uses_gloves, payment_method,
  stall_photo_url, additional_comments, source_timestamp
) VALUES
  (1, '2026-07-23 18:47:07', 'Aminul', '01781099777', 'দারুচিনি হোটেল এন্ড রেস্টুরেন্ট', 'Daffodil Smart City, Birulia, Savar', 'Opposite of YKSG-1, Daffodil Smart City, Birulia, Savar', 'Snacks;Beverage;Meal', 'Daily meal Items', '60', 'Yes', 'No', 'Yes', 'No', NULL, 'https://drive.google.com/u/0/open?usp=forms_web&id=1dRro7Rhjn-khEhcDC2Tvm02Wq5yud_Co', 'More to develop', '2026/07/23 6:47:07 PM GMT+6'),
  (2, '2026-07-23 18:57:05', 'Omar Faruq', '01970825203', 'কুটুম বাড়ি', 'Daffodil Smart City, Birulia, Savar', 'Opposite of YKSG-1Daffodil,  Smart City, Birulia, Savar', 'Beverage;Meal', 'Daily meal items', '60-70/-', 'Yes', 'Yes', 'Yes', 'No', NULL, 'https://drive.google.com/u/0/open?usp=forms_web&id=1hfnw5ZT_BsExgq9reDIcU3Ww8oJ_dOzC', NULL, '2026/07/23 6:57:05 PM GMT+6'),
  (3, '2026-07-23 19:02:59', 'Omar AFaruq', '01920825202', 'কুটুমবাড়ি বিরিয়ানি হাউজ', 'Daffodil Smart City, Birulia, Savar', 'Opposite of YKSG-1Daffodil,  Smart City, Birulia, Savar', 'Beverage', 'খিচুরি, তেহারি, বিরিয়ানি', '১৩০/-', 'Yes', 'Yes', 'Yes', 'Yes', NULL, 'https://drive.google.com/u/0/open?usp=forms_web&id=15r0M6WcwDQlENUxS09BEDmbXlwH7oijU', 'Almost Perfect ', '2026/07/23 7:02:59 PM GMT+6'),
  (4, '2026-07-23 19:09:33', 'মো. আলী আহসান বাদশাহ ', '01969279256', 'অষ্টব্যঞ্জন আপ্যায়ন ', 'Daffodil Smart City, Birulia, Savar', 'Opposite of YKSG-1Daffodil,  Smart City, Birulia, Savar', 'Beverage;Meal', 'দৈনন্দিন খাবার ', '৬০-৭০/-', 'Yes', 'Yes', 'No', 'No', NULL, 'https://drive.google.com/u/0/open?usp=forms_web&id=139cdrP_uogMBKhwmr9Ti04aN2HpV5iFJ', NULL, '2026/07/23 7:09:33 PM GMT+6'),
  (5, '2026-07-23 19:21:11', 'Shahin', '01733957756', 'অতিথি আপ্যায়ন ', 'Daffodil Smart City, Birulia, Savar', 'Opposite of YKSG-1Daffodil,  Smart City, Birulia, Savar', 'Snacks;Beverage;Meal', 'দৈনন্দিন খাবার', '৬০-৭০/-', 'No', 'Yes', 'No', 'No', 'Bkash;Upay;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1yyCB6KJiHBchNmQ2ZDgvN9t5-9JxguOh', 'Lots of option to improve', '2026/07/23 7:21:11 PM GMT+6'),
  (6, '2026-07-23 19:24:26', 'Ashraful Islam', '01860337070', 'Antara', 'Daffodil Smart City, Birulia, Savar', 'Opposite of YKSG-1Daffodil,  Smart City, Birulia, Savar', 'Beverage;Meal', 'Daily meal items ', '60-70/-', 'No', 'Yes', 'No', 'No', 'Bkash;BANGLA QR;Upay;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=10bPeDSafQaNtFzH-bzllQ8Ix_VClipl1', NULL, '2026/07/23 7:24:26 PM GMT+6'),
  (7, '2026-07-24 17:42:21', 'Sohan', '01790803271', 'হাজী বিরিয়ানি হাউজ', 'Daffodil Smart City, Birulia, Savar', 'Opposite of 2no gate, Daffodil Smart City ', 'Beverage', 'তেহারি, মোরহ পোলাও', '১০০/-', 'Yes', 'Yes', 'No', 'No', 'Bkash;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1Z6iYdv3MAovbXcV6MtKS4QZrjcKD1VB7', NULL, '2026/07/24 5:42:21 PM GMT+6'),
  (8, '2026-07-24 17:47:22', 'Rasel Sardar', '01790803271', 'হাজী কাচ্চি ঘর', 'Daffodil Smart City, Birulia, Savar', 'Opposite of 2no gate, Daffodil Smart City', 'Beverage;Dessert', 'তেহারি, কাচ্চি,  মোরগ পোলাও', '100-150/-', 'Yes', 'Yes', 'No', 'No', 'Bkash;Rocket;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1KPMoY2bbHQ4gHu8AK5GFep8l7JhOlJLY', NULL, '2026/07/24 5:47:22 PM GMT+6'),
  (9, '2026-07-24 17:53:23', 'Redwan', '01989653493', 'Vikings Hotel & Restaurant ', 'Daffodil Smart City, Birulia, Savar', 'Opposite of 2no gate, Daffodil Smart City', 'Beverage;Meal', 'দৈনন্দিন খাবার ', '50-60/-', 'Yes', 'Yes', 'Yes', 'No', 'Bkash;BANGLA QR;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1IhRGOTHLJ0xpKx3QL5lZxz7f5kUi97kO', NULL, '2026/07/24 5:53:23 PM GMT+6'),
  (10, '2026-07-24 18:10:31', 'Yeasin Ali Emon', '01631781377', 'তেহারি ঘর', 'Daffodil Smart City, Birulia, Savar', 'Dattapara road, Daffodil Smart City', 'Beverage', 'তেহারি, বিরিয়ানি', '১৩০/-', 'Yes', 'Yes', 'No', 'No', 'Bkash;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1JrT0Zi2zDop9eG3NVaADoJyA3s_geMPW', NULL, '2026/07/24 6:10:31 PM GMT+6'),
  (11, '2026-07-24 18:20:30', 'প্রো: মো: ইলিয়াস হোসেন', '01984271416', 'আল্লাহর দান বিরিয়ানি হাউজ এন্ড ঘরোয়া হোটেল', 'Daffodil Smart City, Birulia, Savar', 'Dattapara road, Daffodil Smart City', 'Snacks;Beverage;Meal', 'দৈনন্দিন খাবার ', '50-60/-', 'Yes', 'Yes', 'No', 'No', 'Bkash;Rocket;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1etPMWBGtFEqitRI6x6rPQiDHIDRhvzA_', NULL, '2026/07/24 6:20:30 PM GMT+6'),
  (12, '2026-07-24 18:26:54', 'প্রো: মো: আলী দেওয়ান', '01605530128', 'দেওয়ান হোটেল এন্ড রেস্টুরেন্টে ', 'Daffodil Smart City, Birulia, Savar', 'Dattapara road, Daffodil Smart City', 'Snacks;Beverage;Dessert;BBQ;Meal', 'দৈনন্দিন খাবার ', '50-70/-', 'No', 'Yes', 'No', 'No', 'Bkash;BANGLA QR;Rocket;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1wuWj-ZZBsYIpHLK6CnwQqex6l2Cp1UlF', 'Have to be cautious about food quality ', '2026/07/24 6:26:54 PM GMT+6'),
  (13, '2026-07-24 18:33:45', 'প্রো: মো: জহির উদ্দিন ', '01953-238169', 'ঢাকা হোটেল এন্ড রেস্টুরেন্ট', 'Daffodil Smart City, Birulia, Savar', 'Dattapara road, Daffodil Smart City', 'Snacks;Beverage;Dessert;BBQ;Meal', 'সকল ধরনের খাবার', '৫০-৮০/-', 'No', 'Yes', 'No', 'No', 'Bkash;BANGLA QR;Rocket;Cash', 'https://drive.google.com/u/0/open?usp=forms_web&id=1GBi5ExvL3-5D-xgP2TbAmLMUYTHhblkH', 'Hygiene issue ', '2026/07/24 6:33:45 PM GMT+6'),
  (14, '2026-07-28 13:54:31', 'Daffodil Family', '3-6100004', 'Green Garden', 'Daffodil Smart City', 'Inside Daffodil International University ', 'Fast Food;Snacks;Beverage;Dessert;BBQ;Meal', 'Every item', '90-120/-', 'Yes', 'Yes', 'No', 'Yes', 'Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=1ji1ra9YNTX9938ImTGPDXiaMapXzYeeC', 'Over hyped ', '2026/07/28 1:54:31 PM GMT+6'),
  (15, '2026-07-28 13:59:25', 'Food Court', '01708484369', 'Amar Food', 'Daffodil Smart City', 'Food Court,  Inside Daffodil International University', 'Fast Food;Snacks;Beverage', 'Snacks item', '30', 'Yes', 'Yes', 'No', 'No', 'Bkash;BANGLA QR;Upay;Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=1mOOPZdf6Igi50RPykD9OkVDuZBrRr72D', NULL, '2026/07/28 1:59:25 PM GMT+6'),
  (16, '2026-07-28 14:12:59', 'Johur Ashik', '01774080508', 'Johurs Food', 'Daffodil Smart City', 'Food Court, Inside Daffodil International University', 'Snacks;Beverage;Meal', 'Daily Meal items', '80-100', 'Yes', 'Yes', 'No', 'No', 'Bkash;Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=14hbDngjuWPc-t6b7QhT_M6zG-ebxbHRP', 'Has rumours ', '2026/07/28 2:12:59 PM GMT+6'),
  (17, '2026-07-28 14:17:28', 'Arif ', '+8801880156835', 'Crape Corner', 'Daffodil Smart City', 'Food Court, Inside Daffodil International University', 'Fast Food;Snacks;Beverage;Meal', 'Every kind of food', '100', 'Yes', 'Yes', 'No', 'Yes', 'Bkash;Upay;Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=1fw86W1aJY4jFq3elg8uTdnJirvXLRZQX', NULL, '2026/07/28 2:17:28 PM GMT+6'),
  (18, '2026-07-28 14:21:33', 'Atif ', '01901041655', 'Atif Agro sweets & bakery', 'Daffodil Smart City', 'Food Court, Inside Daffodil International University', 'Fast Food;Snacks;Beverage;Dessert', 'Sweet Items ', '500', 'Yes', 'Yes', 'No', 'Yes', 'Bkash;Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=1iQmLSL4VB-P-wqsIyqteb82dlgFtEXor', NULL, '2026/07/28 2:21:33 PM GMT+6'),
  (19, '2026-07-28 14:25:03', 'Unknown', '01326710499', 'Paragon Mart', 'Daffodil Smart City', 'Food Court, Inside Daffodil International University', 'Fast Food;Snacks;Beverage;Dessert', 'Fast food', '100', 'Yes', 'Yes', 'No', 'Yes', 'Bkash;Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=1YSYvgDUiow5mZo68CZK8VdmJPVOfb0cB', NULL, '2026/07/28 2:25:03 PM GMT+6'),
  (20, '2026-07-28 14:29:04', 'Unknown ', '01660113813', 'Classio', 'Daffodil Smart City', 'Food Court, Inside Daffodil International University', 'Fast Food;Snacks;Beverage;Dessert;Meal', 'Everything ', '120', 'Yes', 'Yes', 'No', 'No', 'Bkash;Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=1u0fY7NG7P64MstVMUwzYUgkBhouAExAq', NULL, '2026/07/28 2:29:04 PM GMT+6'),
  (21, '2026-07-28 14:32:19', 'Abir Hasan', '01805927355', 'Peribites', 'Daffodil Smart City', 'Food Court, Inside Daffodil International University', 'Fast Food;Beverage;Meal', 'Meal Items', '100', 'Yes', 'Yes', 'No', 'Yes', 'Bkash;Cash;1Card', 'https://drive.google.com/u/0/open?usp=forms_web&id=1YJ3HtVwhfiRwuWqpy8f-XLGpaqFEcjPx', NULL, '2026/07/28 2:32:19 PM GMT+6');

COMMIT;

-- Expected row count:
-- roles 4; street_food_stall_registrations 21;
-- all former synthetic transactional-data tables 0.
