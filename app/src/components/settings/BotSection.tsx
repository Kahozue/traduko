import { useState } from "react";
import { t } from "../../i18n";
import type { DiscordBotConfigDoc } from "../../lib/api/types";
import { Section } from "./Section";
import styles from "./settings.module.css";

function isDigits(value: string): boolean {
  return /^\d+$/.test(value);
}

export function BotSection({
  bot,
  onChange,
}: {
  bot: DiscordBotConfigDoc;
  onChange: (value: DiscordBotConfigDoc | null) => void;
}) {
  const [reveal, setReveal] = useState(false);
  const [guildText, setGuildText] = useState(bot.guild_id);
  const [channelText, setChannelText] = useState(bot.channel_id);
  const [idsText, setIdsText] = useState(() => bot.allowed_user_ids.join(", "));

  function push(
    next: Partial<DiscordBotConfigDoc>,
    texts: { guild?: string; channel?: string; ids?: string } = {},
  ) {
    const guild = (texts.guild ?? guildText).trim();
    const channel = (texts.channel ?? channelText).trim();
    const ids = (texts.ids ?? idsText)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    const valid =
      (guild === "" || isDigits(guild)) &&
      (channel === "" || isDigits(channel)) &&
      ids.every(isDigits);
    if (!valid) {
      onChange(null);
      return;
    }
    onChange({
      ...bot,
      ...next,
      guild_id: guild,
      channel_id: channel,
      allowed_user_ids: ids,
    });
  }

  const guildInvalid = guildText.trim() !== "" && !isDigits(guildText.trim());
  const channelInvalid = channelText.trim() !== "" && !isDigits(channelText.trim());
  const idsInvalid = idsText
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .some((item) => !isDigits(item));

  return (
    <Section
      icon="bot"
      tint="accent"
      title={t("settings.bot")}
      description={t("settings.bot.restartHint")}
    >
      <label className={`${styles.checkItem} ${styles.toggleField}`}>
        <input
          type="checkbox"
          checked={bot.enabled}
          onChange={(event) => push({ enabled: event.target.checked })}
        />
        {t("settings.bot.enabled")}
      </label>
      <div className={styles.fieldRow}>
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.bot.token")}</span>
          <span className={styles.inline}>
            <input
              className={styles.input}
              type={reveal ? "text" : "password"}
              value={bot.bot_token}
              onChange={(event) => push({ bot_token: event.target.value })}
              aria-label={t("settings.bot.token")}
            />
            <button
              type="button"
              className={styles.secondary}
              onClick={() => setReveal((value) => !value)}
            >
              {reveal ? t("settings.hide") : t("settings.reveal")}
            </button>
          </span>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.bot.tokenEnv")}</span>
          <input
            className={styles.input}
            value={bot.bot_token_env}
            onChange={(event) => push({ bot_token_env: event.target.value })}
            aria-label={t("settings.bot.tokenEnv")}
          />
        </label>
      </div>
      <div className={styles.fieldRow}>
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.bot.guildId")}</span>
          <input
            className={styles.input}
            inputMode="numeric"
            value={guildText}
            onChange={(event) => {
              setGuildText(event.target.value);
              push({}, { guild: event.target.value });
            }}
            aria-label={t("settings.bot.guildId")}
          />
          {guildInvalid && (
            <span className={styles.error}>{t("settings.bot.idInvalid")}</span>
          )}
        </label>
        <label className={styles.field}>
          <span className={styles.label}>{t("settings.bot.channelId")}</span>
          <input
            className={styles.input}
            inputMode="numeric"
            value={channelText}
            onChange={(event) => {
              setChannelText(event.target.value);
              push({}, { channel: event.target.value });
            }}
            aria-label={t("settings.bot.channelId")}
          />
          {channelInvalid && (
            <span className={styles.error}>{t("settings.bot.idInvalid")}</span>
          )}
        </label>
      </div>
      <label className={styles.field}>
        <span className={styles.label}>{t("settings.bot.allowedUserIds")}</span>
        <input
          className={styles.input}
          value={idsText}
          onChange={(event) => {
            setIdsText(event.target.value);
            push({}, { ids: event.target.value });
          }}
          aria-label={t("settings.bot.allowedUserIds")}
        />
        {idsInvalid && <span className={styles.error}>{t("settings.bot.idInvalid")}</span>}
      </label>
    </Section>
  );
}
