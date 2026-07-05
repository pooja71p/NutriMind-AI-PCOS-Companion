import math
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("NutriMind Server")

@mcp.tool()
def calculate_bmr_and_bmi(
    weight_kg: float, 
    height_cm: float, 
    age: int, 
    activity_level: str = "lightly_active"
) -> str:
    """Calculates BMI, BMR, and recommended daily calorie intake for weight loss.
    
    Args:
        weight_kg: Weight in kilograms.
        height_cm: Height in centimeters.
        age: Age in years.
        activity_level: One of 'sedentary', 'lightly_active', 'moderately_active', 'very_active'.
    """
    bmi = weight_kg / ((height_cm / 100) ** 2)
    
    # Mifflin-St Jeor Formula for females (PCOS/PMDD specific)
    bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161
    
    activity_factors = {
        "sedentary": 1.2,
        "lightly_active": 1.375,
        "moderately_active": 1.55,
        "very_active": 1.725
    }
    factor = activity_factors.get(activity_level.lower(), 1.375)
    tdee = bmr * factor
    
    # Healthy PCOS weight loss deficit (usually 350-500 kcal)
    target_calories = max(1200, tdee - 400)
    
    # Recommended macros for PCOS (typically higher protein, lower glycemic carbs)
    protein_g = (target_calories * 0.30) / 4  # 30% protein
    fat_g = (target_calories * 0.35) / 9      # 35% healthy fats
    carb_g = (target_calories * 0.35) / 4      # 35% low-GI carbs
    
    return (
        f"Health analysis results:\n"
        f"- BMI: {bmi:.2f}\n"
        f"- BMR: {bmr:.0f} calories/day (minimum energy needed)\n"
        f"- TDEE: {tdee:.0f} calories/day (maintenance energy)\n"
        f"- Target Calorie Intake (Weight Loss): {target_calories:.0f} calories/day\n"
        f"- Suggested PCOS Macros:\n"
        f"  * Protein: {protein_g:.0f}g (30%)\n"
        f"  * Healthy Fats: {fat_g:.0f}g (35%)\n"
        f"  * Low-GI Carbs: {carb_g:.0f}g (35%)\n"
    )

@mcp.tool()
def get_pcos_pmdd_recipes(ingredients: str) -> str:
    """Finds PCOS/PMDD friendly recipes based on ingredients available at home.
    
    Args:
        ingredients: A comma-separated list of ingredients.
    """
    recipe_db = [
        {
            "name": "PCOS Avocado & Egg Salmon Plate",
            "ingredients": ["avocado", "egg", "salmon", "spinach"],
            "calories": 420,
            "protein": "32g",
            "fats": "24g",
            "carbs": "8g (Low-GI)",
            "instructions": "Sear salmon in olive oil. Serve with a boiled egg, half avocado, and fresh spinach."
        },
        {
            "name": "PMDD Mood-Boosting Oatmeal",
            "ingredients": ["oats", "berries", "chia seeds", "walnuts", "greek yogurt"],
            "calories": 380,
            "protein": "18g",
            "fats": "14g",
            "carbs": "45g (High-fiber, low glycemic)",
            "instructions": "Cook oats in almond milk. Top with mixed berries, chia seeds, chopped walnuts, and a scoop of Greek yogurt."
        },
        {
            "name": "Anti-Inflammatory Turmeric Chicken & Quinoa",
            "ingredients": ["chicken", "quinoa", "broccoli", "turmeric", "olive oil"],
            "calories": 480,
            "protein": "38g",
            "fats": "16g",
            "carbs": "35g (High-fiber)",
            "instructions": "Saute chicken breast with turmeric, garlic, and broccoli in olive oil. Serve over cooked quinoa."
        },
        {
            "name": "Hormone-Balancing Berry Green Smoothie",
            "ingredients": ["spinach", "berries", "protein powder", "flaxseeds", "almond milk"],
            "calories": 290,
            "protein": "25g",
            "fats": "8g",
            "carbs": "18g",
            "instructions": "Blend all ingredients until smooth. Flaxseeds provide essential lignans for estrogen balance."
        }
    ]
    
    user_ingredients = [i.strip().lower() for i in ingredients.split(",") if i.strip()]
    matched = []
    
    for r in recipe_db:
        # Check how many ingredients match
        match_count = sum(1 for i in user_ingredients if any(i in ri for ri in r["ingredients"]))
        if match_count > 0:
            matched.append((match_count, r))
            
    # Sort by highest matches
    matched.sort(reverse=True, key=lambda x: x[0])
    
    if not matched:
        # Return all as fallback suggestions
        matched = [(0, r) for r in recipe_db]
        msg = "No exact ingredient matches, but here are some excellent hormone-balancing recipe suggestions:\n\n"
    else:
        msg = f"Found {len(matched)} PCOS/PMDD friendly recipes matching your ingredients:\n\n"
        
    for _, r in matched:
        msg += (
            f"**{r['name']}**\n"
            f"- Ingredients: {', '.join(r['ingredients'])}\n"
            f"- Macros: Calories: {r['calories']}kcal | Protein: {r['protein']} | Fats: {r['fats']} | Carbs: {r['carbs']}\n"
            f"- Steps: {r['instructions']}\n\n"
        )
    return msg

@mcp.tool()
def get_pcos_pmdd_education(topic: str) -> str:
    """Provides science-backed educational explanations of PCOS and PMDD topics.
    
    Args:
        topic: The topic name (e.g. 'insulin resistance', 'cycle syncing', 'inflammation', 'progesterone').
    """
    knowledge = {
        "insulin resistance": (
            "Insulin resistance affects up to 70-80% of PCOS cases. When your cells resist insulin, your pancreas "
            "produces more insulin to compensate. High insulin levels trigger the ovaries to produce excess androgens "
            "(like testosterone), leading to acne, hirsutism, and irregular cycles. Action: Focus on high-fiber foods, "
            "healthy fats, and protein to prevent glucose spikes."
        ),
        "cycle syncing": (
            "Cycle syncing involves adjusting your diet and workouts to match the phases of your menstrual cycle. "
            "For PCOS/PMDD, this means choosing low-intensity exercise (like walking/yoga) during the luteal phase "
            "when progesterone drops, and incorporating strength training during follicular/ovulatory phases when estrogen is higher."
        ),
        "inflammation": (
            "Chronic low-grade inflammation is a primary driver of PCOS. It stimulates androgen production and worsens "
            "insulin resistance. Focus on anti-inflammatory omega-3 fats (salmon, walnuts, chia seeds) and colorful berries."
        ),
        "progesterone": (
            "Progesterone is the calming hormone produced after ovulation. In PCOS, irregular ovulation causes low progesterone, "
            "which can lead to estrogen dominance, anxiety, and sleep disturbances. In PMDD, cells are hypersensitive to "
            "the sudden drop in progesterone during the late luteal phase. Action: Prioritize magnesium-rich foods (spinach, dark chocolate) "
            "and B6 (eggs, poultry)."
        )
    }
    
    topic_cleaned = topic.lower().strip()
    # Find matching key
    for k, v in knowledge.items():
        if k in topic_cleaned or topic_cleaned in k:
            return f"**Education on {k.title()}:**\n{v}"
            
    return (
        f"Here is some general advice on '{topic}': To balance hormones, focus on consistent meals with high-quality protein, "
        f"anti-inflammatory healthy fats, and low glycemic carbs. Ensure 8 hours of sleep and engage in strength training "
        f"to improve insulin sensitivity."
    )

if __name__ == "__main__":
    mcp.run()
