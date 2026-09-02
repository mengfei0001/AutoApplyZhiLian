import argparse
import asyncio
import json
import os
import sys
import time
from playwright.async_api import async_playwright
import random
from datetime import datetime
import logging
import re

# 强制 stdout/stderr 使用 UTF-8 并开启行缓冲，避免 Windows GBK 编码导致主进程（main.py）解码崩溃，
# 同时确保每行日志能实时输出（管道被 main.py 转发到控制台与页面）
if sys.stdout:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass
if sys.stderr:
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

from app_config import get_config
from ai_client import get_ai_client
from dao import apply_record_dao
from dao.blocked_company_dao import blocked_company_dao

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ZhaopinAutomation:
    def __init__(self, headless=False):
        self.headless = headless
        self.context = None
        self.page = None
        self.playwright = None
        self.browser = None
        self.state_file = "zhaopin_state.json"
        # 新版滚动加载模式下已处理的卡片数（用于增量遍历，避免重复处理）
        self.split_processed = 0

        # 应用配置和 AI 客户端（DeepSeek）
        self.config = get_config()
        self.ai = get_ai_client()

        # 使用 DAO 层访问数据库
        self.db = apply_record_dao

        # 确保 SQLite 数据库表结构存在（幂等）
        try:
            from dao.database import init_database
            init_database()
        except Exception as e:
            logger.warning(f"数据库初始化失败: {e}")

        # 从数据库加载应用配置（数据库优先，合并到内存配置）
        try:
            self.config.load_from_db()
        except Exception as e:
            logger.warning(f"从数据库加载配置失败: {e}")
        # 刷新 AI 客户端配置（DeepSeek）
        self.ai = get_ai_client()

        # 搜索URL（从数据库配置读取）
        self.search_url = self.config.get(
            "search_url",
            "https://www.zhaopin.com/sou/jl530/kw01L00O80EO062/p1?sl=15001,25000"
        )
        # 登录成功判断关键词（从数据库配置读取）
        self.login_success_keyword = self.config.get("login_success_keyword", "xxx") or "xxx"

        # 投递统计
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "already_applied": 0,
            "skipped": 0
        }

    async def init_browser(self):
        """初始化浏览器"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=['--start-maximized']
        )

        if os.path.exists(self.state_file):
            print("发现保存的登录状态，尝试加载...")
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                self.context = await self.browser.new_context(
                    storage_state=state,
                    viewport={'width': 1920, 'height': 1080}
                )
                print("登录状态加载成功")
                return True
            except Exception as e:
                print(f"加载登录状态失败: {e}")
                return False
        else:
            print("未找到保存的登录状态，将创建新的上下文")
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080}
            )
            return False

    async def save_state(self):
        """保存登录状态"""
        try:
            state = await self.context.storage_state()
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
            print(f"登录状态已保存到 {self.state_file}")
            return True
        except Exception as e:
            print(f"保存登录状态失败: {e}")
            return False

    async def check_login_status(self):
        """检查登录状态：页面中出现配置的登录成功关键词即认为已登录"""
        try:
            page_content = await self.page.content()
            return self.login_success_keyword in page_content
        except:
            return False

    async def wait_for_login(self):
        """等待用户登录：自动检测页面中是否出现登录成功关键词，出现即视为已登录

        无需用户手动确认，一旦页面中出现登录成功关键词即视为登录成功，
        自动保存登录状态并返回，随后才允许跳转到搜索页面。
        """
        print("\n" + "=" * 60)
        print("请在浏览器中手动登录")
        print("=" * 60)

        # 复用已有页面，避免重复打开新页面
        if self.page is None:
            self.page = await self.context.new_page()

        await self.page.goto("https://www.zhaopin.com/")
        await self.page.wait_for_load_state('networkidle')
        await asyncio.sleep(2)

        print(f"\n正在等待登录（检测页面中出现「{self.login_success_keyword}」即视为登录成功）...")
        print("无需手动确认，请直接在浏览器中完成登录操作...")
        print("=" * 60)

        wait_count = 0
        while True:
            try:
                # 检查当前页面是否已出现登录成功关键词 - 已登录
                if await self.check_login_status():
                    print(f"✅ 检测到「{self.login_success_keyword}」，登录成功！")
                    await asyncio.sleep(2)
                    await self.save_state()
                    return True

                # 未检测到关键词，每 2 秒提示一次等待状态
                wait_count += 1
                print(f"⏳ 尚未登录，继续等待...（已等待 {wait_count * 2} 秒）")

                # 第 6 次（约 12 秒）仍未登录，提示用户尽快登录
                if wait_count == 6:
                    print("🔔 请尽快在浏览器中完成登录！")
                    print("🔔 提示：登录完成后页面会出现「%s」，程序会自动识别并继续" % self.login_success_keyword)

                # 每约 6 秒刷新一次页面，确保登录成功后能及时检测到
                if wait_count % 3 == 0:
                    try:
                        await self.page.reload(wait_until='domcontentloaded')
                        await self.page.wait_for_load_state('networkidle')
                        await asyncio.sleep(2)
                    except Exception as e:
                        logger.warning(f"刷新页面时出错: {e}")

                await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"等待登录时出错: {e}")
                await asyncio.sleep(2)

    async def navigate_to_search(self):
        """导航到搜索页面"""
        print(f"\n正在访问搜索页面...")
        print(f"URL: {self.search_url}")

        await self.page.goto(self.search_url)
        await self.page.wait_for_load_state('networkidle')
        await asyncio.sleep(3)

        print("✅ 搜索页面加载完成（新版分栏布局：左侧列表 + 右侧详情）")

    async def get_job_list(self):
        """获取当前页面的职位列表（新版分栏页面左侧 .job-list-panel 内的 .job-card）"""
        try:
            cards = await self.page.query_selector_all('.job-list-panel .job-card')
            if cards and len(cards) > 0:
                print(f"找到 {len(cards)} 个职位")
                return cards
        except Exception:
            pass

        print("❌ 未找到职位列表")
        return []

    async def extract_job_info(self, job_element):
        """提取新版分栏页面左侧 .job-card 的基础信息"""
        info = {
            "title": "未知",
            "company": "未知",
            "url": None,
            "job_hash2": None,
            "salary": None,
            "location": None,
            "description": None,
            "requirements": None,
            "experience": None,
            "education": None,
            "category": None,
            "registered_capital": None,
            "company_scale": None
        }
        try:
            return await self._extract_job_info_new(job_element, info)
        except Exception as e:
            logger.error(f"提取职位信息失败: {e}")
            return info

    # 学历关键词（新版 .job-card__skill-tag 启发式解析用）
    _EDU_KEYWORDS = ('博士', '硕士', '本科', '大专', '中专', '高中', '初中', '学历不限')
    # 经验关键词模式（如 5-10年 / 3年以上 / 经验不限 / 应届生）
    _EXP_RE = re.compile(r'\d+[-~]\d+年|\d+年以上|\d+年以下|经验不限|应届|在校生|经验应届')

    async def _extract_job_info_new(self, card, info):
        """提取新版分栏页面左侧 .job-card 的基础信息

        新版卡片无 jobdetail 链接（公司链接指向 companydetail），
        因此 url/job_hash2 为空，查重时 DAO 自动回退到 标题+公司名 的 job_hash。
        """
        # 职位标题：.job-card__title-clamp .vue-clamp__text（文本被截断时用 aria-label 补全）
        try:
            title_elem = await card.query_selector('.job-detail-summary__title-text')
            if title_elem:
                info["title"] = ((await title_elem.text_content()) or '').strip()
                if not info["title"]:
                    aria = await title_elem.get_attribute('aria-label')
                    info["title"] = (aria or '').strip()
            if not info["title"] or info["title"] == '未知':
                aria_span = await card.query_selector('.job-card__title-clamp span[aria-label]')
                if aria_span:
                    info["title"] = (await aria_span.get_attribute('aria-label') or '').strip() or info["title"]
        except Exception as e:
            logger.warning(f"提取新版职位标题失败: {e}")

        # 薪资
        try:
            salary_elem = await card.query_selector('.job-card__salary')
            if salary_elem:
                info["salary"] = ((await salary_elem.text_content()) or '').strip()
        except Exception:
            pass

        # 公司名称：.job-card__company-name（title 属性更完整）
        try:
            company_elem = await card.query_selector('.job-card__company-name')
            if company_elem:
                title_attr = await company_elem.get_attribute('title')
                info["company"] = (title_attr or (await company_elem.text_content()) or '').strip()
        except Exception:
            pass

        # 工作地点：.job-card__location span（title 属性更完整）
        try:
            loc_elem = await card.query_selector('.job-card__location span')
            if loc_elem:
                title_attr = await loc_elem.get_attribute('title')
                info["location"] = (title_attr or (await loc_elem.text_content()) or '').strip()
        except Exception:
            pass

        # 技能标签：前两个通常为 学历/经验（部分卡片缺经验），按关键词启发式解析
        try:
            tags = await card.query_selector_all('.job-card__skill-tag')
            for tag in tags[:3]:
                text = ((await tag.text_content()) or '').strip()
                if not text:
                    continue
                if not info["education"] and any(kw in text for kw in self._EDU_KEYWORDS):
                    info["education"] = text
                elif not info["experience"] and self._EXP_RE.search(text):
                    info["experience"] = text
        except Exception:
            pass

        return info

    async def fetch_job_detail_split(self, job_info, job_element):
        """新版分栏页面：点击左侧卡片，从右侧详情面板提取详细信息

        新版页面不再跳转 /jobdetail/xxx.htm，而是右侧 .job-detail-panel 展开详情。
        注意：新版详情面板无"注册资本"信息，仅有公司规模（如 20-99人）与行业。
        """
        try:
            # 1. 点击左侧卡片，触发右侧详情渲染
            await job_element.scroll_into_view_if_needed()
            await job_element.click()
            # 等待右侧详情标题出现并稳定
            await self.page.wait_for_selector('.job-detail-summary__title-text', timeout=8000)
            await asyncio.sleep(1.5)

            panel = await self.page.query_selector('.job-detail-panel')
            if not panel:
                logger.warning("右侧详情面板未渲染")
                return job_info

            print(f"  ✅ 右侧详情已展开: {job_info.get('title')}")

            # 2. 职位标题
            try:
                title_elem = await panel.query_selector('.job-detail-summary__title-text')
                if title_elem:
                    text = ((await title_elem.text_content()) or '').strip()
                    if text:
                        job_info['title'] = text
            except Exception:
                pass

            # 3. 薪资
            try:
                salary_elem = await panel.query_selector('.job-detail-summary__salary')
                if salary_elem:
                    text = ((await salary_elem.text_content()) or '').strip()
                    if text:
                        job_info['salary'] = text
            except Exception:
                pass

            # 4. 标签列表（地点/经验/学历，如 北京·海淀区 / 经验不限 / 本科）
            try:
                tags = await panel.query_selector_all('.job-detail-summary__tags li span')
                for tag in tags:
                    text = ((await tag.text_content()) or '').strip()
                    if not text:
                        continue
                    if any(kw in text for kw in self._EDU_KEYWORDS):
                        job_info['education'] = text
                    elif self._EXP_RE.search(text):
                        job_info['experience'] = text
                    elif '·' in text or not job_info.get('location'):
                        # 地点标签（如 北京·海淀区），或首个未知标签视为地点
                        if not job_info.get('location') or '·' in text:
                            job_info['location'] = text.replace('·', ' ').strip()
            except Exception as e:
                logger.warning(f"提取新版详情标签失败: {e}")

            # 5. 公司名称
            try:
                company_elem = await panel.query_selector('.job-detail-summary__company-name')
                if company_elem:
                    text = ((await company_elem.text_content()) or '').strip()
                    if text:
                        job_info['company'] = text
            except Exception:
                pass

            # 6. 公司规模/行业（如 "20-99人 · 商务服务业"）
            try:
                desc_elem = await panel.query_selector('.job-company-info__desc')
                if desc_elem:
                    text = ((await desc_elem.text_content()) or '').strip()
                    if text:
                        m = re.search(r'([\d\-~]+人)', text)
                        if m:
                            job_info['company_scale'] = m.group(1)
                        # 行业作为 category 补充（清洗掉"已审核"等状态标记与多余空白）
                        parts = [p.strip() for p in text.split('·') if p.strip()]
                        if parts and not job_info.get('category'):
                            raw_cat = re.sub(r'\s+', ' ', parts[-1])
                            raw_cat = raw_cat.replace('已审核', '').replace('认证', '').strip()
                            if raw_cat:
                                job_info['category'] = raw_cat
            except Exception:
                pass

            # 7. 岗位描述
            try:
                desc_elem = await panel.query_selector('.job-description__content')
                if desc_elem:
                    text = ((await desc_elem.text_content()) or '').strip()
                    if len(text) > 30:
                        job_info['description'] = text
            except Exception:
                pass

            # 打印提取到的关键信息
            print(f"  职位: {job_info['title']}")
            print(f"  薪资: {job_info.get('salary')}")
            print(f"  公司: {job_info.get('company')}")
            print(f"  地点: {job_info.get('location')}")
            print(f"  经验: {job_info.get('experience')}")
            print(f"  学历: {job_info.get('education')}")
            print(f"  公司规模/人数: {job_info.get('company_scale') or '未获取'}")
            print(f"  注册资本: 未获取（新版页面无此信息）")
            if job_info.get('description'):
                desc_preview = job_info['description'][:100] + "..." if len(job_info['description']) > 100 else \
                    job_info['description']
                print(f"  描述预览: {desc_preview}")

            return job_info

        except Exception as e:
            logger.error(f"新版详情提取失败: {e}")
            return job_info

    async def apply_job_split(self, job_element, index, fetch_detail=True):
        """新版分栏页面投递单个职位：点击卡片 -> 右侧详情 -> 右侧投递按钮

        Returns:
            True=投递成功 / "already_applied"=已投递/已沟通被跳过 / "limit_reached"=今日投递已达上限 / False=其他情况未投递
        """
        print(f"\n{'=' * 50}")
        print(f"处理第 {index} 个职位（新版分栏模式）")

        # 提取卡片基础信息
        job_info = await self.extract_job_info(job_element)
        print(f"职位: {job_info['title']}")
        print(f"公司: {job_info['company']}")
        if job_info.get('salary'):
            print(f"薪资: {job_info['salary']}")
        if job_info.get('location'):
            print(f"地点: {job_info['location']}")

        # 检查是否已经在记录中
        if self.db.is_job_applied(job_info):
            print(f"⏭️  该职位已在投递记录中，跳过")
            self.stats["already_applied"] += 1
            self.stats["skipped"] += 1
            return "already_applied"

        # 点击卡片展开右侧详情并提取
        if fetch_detail:
            job_info = await self.fetch_job_detail_split(job_info, job_element)
            self.db.add_record(job_info, "detail_fetched")

            # ========== 「继续沟通」= 已投递检查 ==========
            # 右侧详情面板出现「继续沟通」按钮（job-detail-summary__prechat），
            # 表示该职位此前已投递过，直接跳过并访问下一条
            try:
                prechat_btn = await self.page.query_selector(
                    'button:has-text("继续沟通")'
                )
                if prechat_btn and await prechat_btn.is_visible():
                    print(f"⏭️ 详情页出现「继续沟通」，该职位已投递过，跳过")
                    self.stats["already_applied"] += 1
                    self.stats["skipped"] += 1
                    self.db.add_record(job_info, "already_applied", "详情页存在「继续沟通」按钮（已投递过）")
                    return "already_applied"
            except Exception as e:
                logger.warning(f"检查「继续沟通」按钮失败: {e}")

        # ========== 屏蔽公司检查 ==========
        if self.is_blocked_company(job_info):
            print(f"⛔ 公司 {job_info.get('company')} 在屏蔽列表中，跳过")
            self.stats["skipped"] += 1
            self.db.add_record(job_info, "blocked_company", "公司在屏蔽列表中")
            return False

        # ========== 地点检查 ==========
        if self.is_location_mismatch(job_info):
            print(f"📍 地点 {job_info.get('location')} 不在允许列表中，跳过")
            self.stats["skipped"] += 1
            self.db.add_record(job_info, "location_mismatch", f"地点不在允许列表中: {job_info.get('location')}")
            return False

        # ========== 薪资预判断（减少 DeepSeek 调用次数） ==========
        salary_check = self.check_salary_match(job_info.get('salary'))
        if salary_check is False:
            exp_range = self.config.get("salary_range", "")
            print(f"💰 职位薪资 {job_info.get('salary')} 不满足期望 {exp_range}，跳过")
            self.stats["skipped"] += 1
            self.db.add_record(job_info, "not_qualified", f"薪资不匹配: {job_info.get('salary')} vs 期望 {exp_range}")
            return False
        elif salary_check is True:
            print(f"💰 职位薪资 {job_info.get('salary')} 满足期望，继续")
        else:
            print(f"💰 职位薪资 {job_info.get('salary')} 无法解析，交由 DeepSeek 判断")

        # ========== DeepSeek 资格判断 ==========
        qualified, reason, q_status = await self.check_qualification(job_info)
        if q_status == "keyword_filtered":
            print(f"🚫 命中过滤关键词，跳过（未调用 AI）")
            self.stats["skipped"] += 1
            self.db.add_record(job_info, "keyword_filtered", reason)
            return False
        if q_status == "not_qualified":
            print(f"⏭️  DeepSeek 判定不满足投递要求，跳过")
            self.stats["skipped"] += 1
            self.db.add_record(job_info, "not_qualified", reason)
            return False
        elif q_status is None and not qualified:
            print(f"❌ DeepSeek 判断出错且未启用，不投递")
            self.stats["failed"] += 1
            self.db.add_record(job_info, "failed", reason)
            return False

        # ========== 在右侧面板查找投递按钮 ==========
        apply_button = None
        try:
            apply_selectors = [
                'button:has-text("立即投递")'
            ]
            for selector in apply_selectors:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible():
                    apply_button = btn
                    break
        except Exception as e:
            logger.warning(f"查找新版投递按钮失败: {e}")

        if not apply_button:
            print("❌ 右侧详情未找到投递按钮")
            self.stats["failed"] += 1
            self.db.add_record(job_info, "failed", "未找到投递按钮")
            return False

        # 检查按钮状态（已投递/禁用）
        try:
            btn_text = ((await apply_button.text_content()) or '').strip()
            if '已投递' in btn_text or '已申请' in btn_text:
                print(f"⏭️  该职位已投递过（按钮状态: {btn_text}），跳过")
                self.stats["already_applied"] += 1
                self.stats["skipped"] += 1
                self.db.add_record(job_info, "already_applied")
                return "already_applied"
            if await apply_button.is_disabled():
                print(f"⏭️  投递按钮不可用（{btn_text}），跳过")
                self.stats["skipped"] += 1
                self.db.add_record(job_info, "already_applied", f"按钮不可用: {btn_text}")
                return "already_applied"
        except Exception:
            pass

        # ========== 点击投递 ==========
        try:
            print("点击右侧投递按钮...")
            await apply_button.click()
            await asyncio.sleep(2)

            # 处理确认弹窗（简历选择/确认投递）
            success = await self.handle_confirm_dialog(self.page)

            # 检测到「今日投递已超过上限」：终止后续投递
            if success == "limit_reached":
                self.daily_limit_reached = True
                print("🛑 今日投递已达上限，停止本次投递任务")
                return "limit_reached"

            # 投递后可能打开新标签页，统一关闭（仅保留搜索页）
            await self.close_extra_pages([self.page])

            if success:
                print(f"✅ 投递成功: {job_info['title']}")
                self.stats["success"] += 1
                self.db.add_record(job_info, "success")
                return True
            else:
                print(f"❌ 投递失败: {job_info['title']}")
                self.stats["failed"] += 1
                self.db.add_record(job_info, "failed", "投递失败")
                return False

        except Exception as e:
            error_msg = str(e)
            print(f"点击投递按钮时出错: {error_msg}")
            self.stats["failed"] += 1
            self.db.add_record(job_info, "failed", error_msg)
            return False

    async def close_extra_pages(self, keep_pages):
        """关闭除 keep_pages 之外的所有标签页

        投递成功后智联招聘会自动打开"投递成功"页面（新标签页），
        如果不关闭会越积越多。此方法统一清理这类多余标签页。
        """
        try:
            current_pages = list(self.context.pages)
            for page in current_pages:
                if page not in keep_pages:
                    try:
                        await page.close()
                        print("  🧹 已关闭投递后自动打开的额外标签页")
                    except Exception as e:
                        logger.warning(f"关闭额外标签页失败: {e}")
        except Exception as e:
            logger.warning(f"清理额外标签页时出错: {e}")

    def is_blocked_company(self, job_info):
        """检查公司是否在屏蔽列表中（从 blocked_companies 表读取，子串匹配）"""
        company = job_info.get("company", "")
        return blocked_company_dao.is_blocked(company)

    def is_location_mismatch(self, job_info):
        """检查工作地点是否在允许的地点列表中（列表非空时启用过滤）"""
        locations = self.config.get("locations", [])
        if not locations:
            return False
        location = job_info.get("location", "")
        for loc in locations:
            loc = loc.strip()
            if not loc:
                continue
            if loc in location or location in loc:
                return False
        return True

    # 薪资数字提取（如 1.2 / 16000）
    _SALARY_NUM_RE = re.compile(r'(\d+(?:\.\d+)?)')

    def parse_salary(self, text):
        """解析薪资文本，统一转换为「元/月」，返回 (min_yuan, max_yuan)；无法解析返回 None

        支持格式：1.2-1.6万 / 1.2-1.6万·13薪 / 9000-16000元 / 1万-1.5万 / 15-20K / 2万以上
        说明：13薪不影响月薪范围（仍按 1.2-1.6万 元/月）；年薪按 /12 换算为月薪。
        """
        if not text:
            return None
        s = str(text).strip()
        # 无法用区间表达的（面议 / 日薪 / 时薪 / 按件 等）交 DeepSeek 判断
        if '面议' in s or '日' in s or '小时' in s or '件' in s or '单' in s:
            return None
        # 剔除「X薪」（如 13薪）中的数字，避免误作薪资区间
        s2 = re.sub(r'\d+(?:\.\d+)?薪', '', s)
        nums = self._SALARY_NUM_RE.findall(s2)
        if not nums:
            return None

        # 单位换算（默认元）
        if '万' in s:
            unit = 10000
        elif '千' in s:
            unit = 1000
        elif 'k' in s.lower():
            unit = 1000
        else:
            unit = 1

        # 年薪 → 月薪
        per_year = ('年薪' in s) or ('/年' in s)
        values = [float(n) * unit for n in nums]
        if per_year:
            values = [v / 12 for v in values]

        lo, hi = min(values), max(values)
        # 「以上 / +」只有下限；「以下」只有上限
        if '以上' in s or s.endswith('+'):
            hi = None
        elif '以下' in s:
            lo = 0
        return (lo, hi)

    def check_salary_match(self, salary_text):
        """预判断职位薪资是否满足期望薪资范围（减少 DeepSeek 调用次数）

        期望薪资范围取配置 salary_range（元，如 "15000-25000"，可只填下限）。
        规则：职位薪资区间与期望区间有重叠即视为满足。

        Returns:
            True=满足 / False=不满足 / None=无法解析（交由 DeepSeek 判断）
        """
        job = self.parse_salary(salary_text)
        if not job:
            return None
        exp = self.parse_salary(self.config.get("salary_range", ""))
        if not exp:
            return None

        jmin, jmax = job
        emin, emax = exp
        if jmax is None:
            jmax = float('inf')
        if emax is None:
            emax = float('inf')
        return max(jmin, emin) <= min(jmax, emax)

    async def check_qualification(self, job_info):
        """使用已启用的 AI 模型（DeepSeek）判断职位是否满足投递要求

        Returns:
            (ok, reason, status): (bool, str, str)
            - ok: 是否满足投递要求
            - reason: 判断理由/错误信息
            - status: 'qualified' / 'not_qualified' / 'keyword_filtered' / None(未启用或出错)
        """
        # 关键词过滤：标题/内容命中配置的关键词则直接跳过，不调用 AI 模型
        from keyword_filter import split_keywords, match_filter_keyword
        keywords = split_keywords(self.config.get("filter_keywords", ""))
        hit = match_filter_keyword(keywords, job_info)
        if hit:
            print(f"🚫 命中过滤关键词「{hit}」，直接跳过（不调用 AI）")
            return False, f"命中过滤关键词: {hit}", "keyword_filtered"

        if self.ai is None or not self.ai.is_ready:
            print("  ⚠️ AI 模型未启用或未配置 API Key，跳过资格判断")
            return True, "AI 模型未启用", None

        print("  🤖 正在调用 AI 模型判断投递资格...")
        qualified, reason = self.ai.check_qualification(job_info)
        if qualified is None:
            print(f"  ⚠️ AI 模型判断失败: {reason}")
            return True, reason, None

        if qualified:
            print(f"  ✅ AI 模型判断满足投递要求: {reason}")
            return True, reason, "qualified"
        else:
            print(f"  ❌ AI 模型判断不满足投递要求: {reason}")
            return False, reason, "not_qualified"

    async def handle_confirm_dialog(self, page=None):
        """处理确认弹窗

        Args:
            page: 可选，要处理的页面对象；默认使用 self.page

        Returns:
            True=已确认 / False=未确认 / "limit_reached"=今日投递已达上限（终止整个投递）
        """
        page = page or self.page
        try:
            await asyncio.sleep(1)

            # 检测「今日投递已超过上限」弹框：出现则终止后续投递
            try:
                content = await page.content()
                for kw in ["今日投递已超过上限", "已超过今日投递", "今日投递已达上限", "投递次数已达上限"]:
                    if kw in content:
                        print("🚫 检测到「今日投递已超过上限」，终止后续投递")
                        return "limit_reached"
            except Exception:
                pass

            # 处理投递成功弹框「已向对方发送简历和打招呼语」：
            # 点击关闭按钮（X）或「留在此页」，留在当前列表页继续处理，避免误点「继续沟通」跳转到聊天页
            try:
                greeting_modal = await page.query_selector('.deliver-greeting-modal__box')
                if greeting_modal and await greeting_modal.is_visible():
                    print("检测到投递成功弹框「已向对方发送简历和打招呼语」，关闭弹框")
                    close_btn = await greeting_modal.query_selector(
                        '.deliver-greeting-modal__close, '
                        'button:has-text("留在此页")'
                    )
                    if close_btn and await close_btn.is_visible():
                        await close_btn.click()
                        print("已关闭投递成功弹框")
                    await asyncio.sleep(1)
                    return True
            except Exception as e:
                logger.warning(f"关闭投递成功弹框失败: {e}")

            confirm_selectors = [
                'button:has-text("确定")',
                'button:has-text("确认")',
                '.confirm-btn',
                '.dialog-confirm',
                '.btn-confirm',
                'button:has-text("继续")',
                '.modal-footer button:last-child'
            ]

            for selector in confirm_selectors:
                try:
                    confirm_btn = await page.query_selector(selector)
                    if confirm_btn and await confirm_btn.is_visible():
                        # await confirm_btn.click()
                        print("已点击确认按钮")
                        await asyncio.sleep(1)
                        return True
                except:
                    continue

            success_msgs = await page.query_selector_all(
                '.success-msg, .tip-success, .apply-success'
            )
            if success_msgs:
                print("检测到成功提示信息")
                return True

            applied_indicator = await page.query_selector(
                '.applied, .already-applied, [class*="applied"]'
            )
            if applied_indicator:
                print("职位已投递")
                return True

            return True

        except Exception as e:
            logger.error(f"处理弹窗时出错: {e}")
            return True

    async def _count_split_cards(self) -> int:
        """统计新版左侧列表当前卡片数量"""
        try:
            cards = await self.page.query_selector_all('.job-list-panel .job-card')
            return len(cards)
        except Exception:
            return 0

    async def _scroll_split_list(self):
        """新版分栏页滚动加载：优先滚左侧列表容器；容器随 window 滚动时用真实滚轮渐进滚动

        注意：智联新版左侧列表通常不独立滚动（overflow: visible），整个页面随 window 滚动，
        需用真实滚轮事件（mouse.wheel）渐进滚动才能触发下拉加载；直接设置 scrollTop 无效。
        """
        # 1. 优先尝试滚动左侧列表容器（部分新版布局列表自身滚动）
        for sel in ['.job-list-panel', '.job-split-layout__left', '.job-list-sort-scroll']:
            try:
                el = await self.page.query_selector(sel)
                if el:
                    moved = await el.evaluate('''e => {
                        if (e.scrollHeight > e.clientHeight + 20) {
                            e.scrollTop = e.scrollHeight;
                            return true;
                        }
                        return false;
                    }''')
                    if moved:
                        return
            except Exception:
                continue

        # 2. 列表随 window 滚动：把鼠标移到左侧列表区域，用真实滚轮渐进滚动触发加载
        try:
            await self.page.mouse.move(500, 850)
        except Exception:
            pass
        for _ in range(20):
            try:
                y0 = await self.page.evaluate('window.scrollY')
                await self.page.mouse.wheel(0, 800)
                await asyncio.sleep(0.4)
                y1 = await self.page.evaluate('window.scrollY')
            except Exception:
                break
            # scrollY 不再增加说明已滚到底，停止
            if y1 <= y0:
                break

    async def _next_page_new(self):
        """新版分栏页面翻页：优先滚动加载更多卡片，其次查找分页按钮

        Returns:
            True=还有更多职位（卡片增加或已点击下一页），False=已到末尾
        """
        try:
            before = await self._count_split_cards()

            # 1. 滚动列表触发下拉加载
            await self._scroll_split_list()
            await asyncio.sleep(3)
            after = await self._count_split_cards()
            if after > before:
                print(f"📜 滚动加载成功: {before} -> {after} 个职位")
                return True

            # 2. 再滚动一次（部分页面需要多次触发）
            await self._scroll_split_list()
            await asyncio.sleep(3)
            after = await self._count_split_cards()
            if after > before:
                print(f"📜 滚动加载成功: {before} -> {after} 个职位")
                return True

            # 3. 查找分页按钮（iview 分页组件等）
            page_selectors = [
                'li[class*="page-next"] a',
                'li[class*="page-next"]',
                '.ivu-page-next',
                'button:has-text("下一页")',
                'a:has-text("下一页")',
            ]
            for selector in page_selectors:
                try:
                    next_btn = await self.page.query_selector(selector)
                    if next_btn and await next_btn.is_visible():
                        cls = str(await next_btn.get_attribute('class') or '')
                        disabled = await next_btn.get_attribute('disabled') or \
                                   await next_btn.get_attribute('aria-disabled')
                        if disabled or 'disabled' in cls:
                            print("已到最后一页")
                            return False
                        print("点击下一页按钮...")
                        await next_btn.click()
                        # 分页按钮翻页后列表清空重建，重置已处理计数
                        self.split_processed = 0
                        await asyncio.sleep(3)
                        return True
                except Exception:
                    continue

            print("新版列表无更多职位")
            return False

        except Exception as e:
            logger.error(f"新版翻页失败: {e}")
            return False

    def print_db_stats(self):
        """打印数据库统计信息"""
        try:
            total = self.db.get_total_count()
            print(f"\n📊 数据库总记录: {total} 条")

            # 获取最近7天统计
            stats = self.db.get_statistics(7)
            if stats:
                print("\n📈 最近7天统计:")
                print("-" * 60)
                for stat in stats:
                    print(f"  {stat['stat_date']}: 总计{stat['total_applied']} | "
                          f"成功{stat['success_count']} | "
                          f"失败{stat['failed_count']} | "
                          f"跳过{stat['skipped_count']} | "
                          f"成功率{stat['success_rate']}%")

            # 获取最近记录
            recent = self.db.get_recent_records(5)
            if recent:
                print("\n📝 最近5条投递记录:")
                print("-" * 60)
                for record in recent:
                    status_icon = "✅" if record['status'] == 'success' else "❌"
                    print(f"  {status_icon} {record['job_title']} - {record['company_name']}")
                    print(f"     状态: {record['status']} | 时间: {record['apply_time']}")
                    if record.get('description_preview'):
                        print(f"     描述: {record['description_preview']}...")

        except Exception as e:
            logger.error(f"打印统计数据失败: {e}")

    async def run(self, fetch_detail=True):
        """主运行流程

        Args:
            fetch_detail: 是否爬取职位详情（默认True）
        """
        try:
            print("=" * 60)
            print("智联招聘自动投递工具 (SQLite版 - 支持详情爬取)")
            print("=" * 60)
            print(f"📋 详情爬取: {'开启' if fetch_detail else '关闭'}")

            # 显示数据库统计
            self.print_db_stats()

            # 1. 初始化浏览器
            has_state = await self.init_browser()

            # 2. 处理登录（自动检测页面中是否出现登录成功关键词）
            if not has_state:
                # 无保存登录状态，打开首页等待登录
                login_success = await self.wait_for_login()
                if not login_success:
                    print("登录失败，程序退出")
                    return False
            else:
                self.page = await self.context.new_page()
                await self.page.goto("https://www.zhaopin.com/")
                await self.page.wait_for_load_state('networkidle')
                await asyncio.sleep(2)

                auto_login_ok = await self.check_login_status()
                if auto_login_ok:
                    print(f"✅ 检测到「{self.login_success_keyword}」，登录状态有效")
                else:
                    print("⏳ 保存的登录状态可能已失效，等待重新登录...")
                    await self.wait_for_login()

            # 3. 导航到搜索页面
            await self.navigate_to_search()

            # 4. 开始遍历投递
            page_num = 1
            total_applied = 0
            self.daily_limit_reached = False  # 今日投递上限标记
            max_apply_count = int(self.config.get("max_apply_count", 0) or 0)
            if max_apply_count > 0:
                print(f"🎯 本次投递数量上限: {max_apply_count} 个（不包括已投递的）")

            while True:
                # 检测到「今日投递已超过上限」：终止后续投递
                if self.daily_limit_reached:
                    print("\n🚫 今日投递已超过上限，终止本次投递")
                    break
                # 检查是否达到投递数量上限
                if 0 < max_apply_count <= total_applied:
                    print(f"\n✅ 已达到投递数量上限（{max_apply_count} 个），停止投递")
                    break
                print(f"\n{'=' * 60}")
                print(f"第 {page_num} 页")
                print(f"{'=' * 60}")

                jobs = await self.get_job_list()

                if not jobs:
                    print("当前页没有职位")
                    break

                # 滚动加载模式：跳过已处理过的卡片，只处理新增的
                start_index = self.split_processed
                pending = jobs[start_index:]
                if not pending:
                    print("没有新的职位需要处理")
                    if not await self._next_page_new():
                        print("所有页面处理完成！")
                        break
                    page_num += 1
                    continue

                print(f"\n开始投递当前页 {len(pending)} 个职位（从第 {start_index + 1} 个开始）...")
                print(f"当前数据库记录: {self.db.get_total_count()} 条")

                result = None
                for i, job in enumerate(pending, start_index + 1):
                    # 上一条是已投递/已沟通被跳过时，快速等待0.3秒，加快扫描
                    if result == "already_applied":
                        delay = 0.3
                        print("\n上一条为已投递/已沟通，等待0.3秒后继续...")
                    else:
                        delay = random.uniform(3, 8)
                        print(f"\n等待 {delay:.1f} 秒后继续...")
                    await asyncio.sleep(delay)

                    result = await self.apply_job_split(job, i, fetch_detail)
                    self.stats["total"] += 1
                    self.split_processed += 1

                    # 检测到「今日投递已超过上限」：终止整个投递任务
                    if result == "limit_reached":
                        self.daily_limit_reached = True
                        break

                    if result is True:
                        total_applied += 1
                        # 投递成功后再次检查是否达到上限
                        if 0 < max_apply_count <= total_applied:
                            print(f"\n✅ 已达到投递数量上限（{max_apply_count} 个），停止投递")
                            break

                    # 每投递3个职位显示一次统计
                    if total_applied % 3 == 0 and total_applied > 0:
                        print(f"\n📊 当前投递统计:")
                        print(f"  本批成功: {self.stats['success']}")
                        print(f"  总记录: {self.db.get_total_count()}")

                    # 每投递5个职位休息一下
                    if total_applied % 5 == 0 and total_applied > 0:
                        print(f"\n已投递 {total_applied} 个职位，休息15秒...")
                        await asyncio.sleep(15)

                self.print_stats()

                print(f"\n第 {page_num} 页处理完成")

                if not await self._next_page_new():
                    print("所有页面处理完成！")
                    break

                page_num += 1

                print("翻页成功，休息5秒...")
                await asyncio.sleep(5)

            # 5. 最终统计
            self.print_final_stats()
            self.print_db_stats()

            print("\n程序执行完成，浏览器将在30秒后关闭...")
            await asyncio.sleep(30)

            return True

        except Exception as e:
            logger.error(f"程序运行出错: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # 清理资源
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

    def print_stats(self):
        """打印当前统计"""
        print(f"\n📊 当前统计:")
        print(f"  已处理: {self.stats['total']}")
        print(f"  ✅ 成功: {self.stats['success']}")
        print(f"  ❌ 失败: {self.stats['failed']}")
        print(f"  ⏭️  跳过(已投递): {self.stats['already_applied']}")
        print(f"  数据库总记录: {self.db.get_total_count()}")

    def print_final_stats(self):
        """打印最终统计"""
        print("\n" + "=" * 60)
        print("🎯 投递完成！最终统计:")
        print("=" * 60)
        print(f"总处理职位数: {self.stats['total']}")
        print(f"✅ 投递成功: {self.stats['success']}")
        print(f"❌ 投递失败: {self.stats['failed']}")
        print(f"⏭️  跳过(已投递): {self.stats['already_applied']}")
        print(f"📝 数据库总记录: {self.db.get_total_count()}")

        if self.stats['total'] > 0:
            success_rate = self.stats['success'] / (self.stats['total'] - self.stats['already_applied']) * 100
            print(f"成功率: {success_rate:.1f}%")
        else:
            print("无投递记录")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='智联招聘自动投递工具')
    parser.add_argument('--headless', action='store_true',
                        help='无头模式（不显示浏览器窗口）')
    args = parser.parse_args()

    automation = ZhaopinAutomation(headless=args.headless)

    # 完整投递模式
    asyncio.run(automation.run(fetch_detail=True))


if __name__ == "__main__":
    main()