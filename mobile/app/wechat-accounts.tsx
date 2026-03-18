import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  Alert,
  RefreshControl,
  TextInput as RNTextInput,
} from 'react-native';
import {
  Text,
  Card,
  Button,
  Switch,
  useTheme,
  Chip,
  IconButton,
  Dialog,
  Portal,
  TextInput,
  Divider,
  ActivityIndicator,
  FAB,
  Snackbar,
} from 'react-native-paper';
import { Stack, router } from 'expo-router';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { api } from '@/services/api';

interface WechatAccount {
  id: string;
  name: string;
  biz: string;
  description?: string;
  category: string;
  is_preset: boolean;
  enabled: boolean;
  last_fetched_at?: string;
  total_articles: number;
  fetch_fail_count: number;
  added_at?: string;
  rsshub_url?: string;
}

interface PresetAccount {
  name: string;
  biz: string;
  description: string;
  category: string;
}

export default function WechatAccountsScreen() {
  const theme = useTheme();

  const [accounts, setAccounts] = useState<WechatAccount[]>([]);
  const [presets, setPresets] = useState<PresetAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // 添加公众号对话框
  const [addDialogVisible, setAddDialogVisible] = useState(false);
  const [addMode, setAddMode] = useState<'manual' | 'link' | 'preset'>('manual');
  const [newName, setNewName] = useState('');
  const [newBiz, setNewBiz] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newCategory, setNewCategory] = useState('财经');
  const [linkInput, setLinkInput] = useState('');
  const [extracting, setExtracting] = useState(false);

  // 测试采集
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<any>(null);
  const [testDialogVisible, setTestDialogVisible] = useState(false);

  // Snackbar
  const [snackVisible, setSnackVisible] = useState(false);
  const [snackMessage, setSnackMessage] = useState('');

  const showSnack = (msg: string) => {
    setSnackMessage(msg);
    setSnackVisible(true);
  };

  // ==================== 数据加载 ====================

  const loadAccounts = useCallback(async () => {
    try {
      const data = await api.getWechatAccounts();
      setAccounts(data);
    } catch (error) {
      console.error('加载公众号列表失败:', error);
    }
  }, []);

  const loadPresets = useCallback(async () => {
    try {
      const data = await api.getWechatPresets();
      setPresets(data);
    } catch (error) {
      console.error('加载预置列表失败:', error);
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await Promise.all([loadAccounts(), loadPresets()]);
      setLoading(false);
    };
    init();
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await loadAccounts();
    setRefreshing(false);
  };

  // ==================== 操作 ====================

  const handleToggle = async (account: WechatAccount) => {
    try {
      await api.toggleWechatAccount(account.id);
      setAccounts((prev) =>
        prev.map((a) =>
          a.id === account.id ? { ...a, enabled: !a.enabled } : a
        )
      );
      showSnack(`${account.enabled ? '已禁用' : '已启用'} ${account.name}`);
    } catch (error) {
      showSnack('操作失败');
    }
  };

  const handleDelete = (account: WechatAccount) => {
    Alert.alert(
      '确认删除',
      `确定要删除公众号「${account.name}」吗？`,
      [
        { text: '取消', style: 'cancel' },
        {
          text: '删除',
          style: 'destructive',
          onPress: async () => {
            try {
              await api.deleteWechatAccount(account.id);
              setAccounts((prev) => prev.filter((a) => a.id !== account.id));
              showSnack(`已删除 ${account.name}`);
            } catch (error) {
              showSnack('删除失败');
            }
          },
        },
      ]
    );
  };

  const handleAdd = async () => {
    if (!newName.trim() || !newBiz.trim()) {
      showSnack('请填写公众号名称和 biz');
      return;
    }
    try {
      await api.addWechatAccount({
        name: newName.trim(),
        biz: newBiz.trim(),
        description: newDesc.trim() || undefined,
        category: newCategory,
      });
      setAddDialogVisible(false);
      resetAddForm();
      await loadAccounts();
      showSnack(`已添加 ${newName}`);
    } catch (error: any) {
      showSnack(error?.message || '添加失败');
    }
  };

  const handleExtractBiz = async () => {
    if (!linkInput.trim()) {
      showSnack('请粘贴微信文章链接');
      return;
    }
    setExtracting(true);
    try {
      const result = await api.extractWechatBiz(linkInput.trim());
      setNewBiz(result.biz);
      setAddMode('manual');
      showSnack(`提取成功: ${result.biz}`);
    } catch (error: any) {
      showSnack(error?.message || '提取失败，请检查链接');
    }
    setExtracting(false);
  };

  const handleTestFetch = async (account: WechatAccount) => {
    setTestingId(account.id);
    try {
      const result = await api.testWechatFetch(account.id);
      setTestResult(result);
      setTestDialogVisible(true);
    } catch (error) {
      showSnack('测试采集失败');
    }
    setTestingId(null);
  };

  const resetAddForm = () => {
    setNewName('');
    setNewBiz('');
    setNewDesc('');
    setNewCategory('财经');
    setLinkInput('');
    setAddMode('manual');
  };

  // 未添加的预置公众号
  const existingBizSet = new Set(accounts.map((a) => a.biz));
  const availablePresets = presets.filter((p) => !existingBizSet.has(p.biz));

  // ==================== 渲染 ====================

  if (loading) {
    return (
      <>
        <Stack.Screen options={{ title: '公众号订阅' }} />
        <View style={[styles.center, { backgroundColor: theme.colors.background }]}>
          <ActivityIndicator size="large" />
          <Text style={{ marginTop: 16 }}>加载中...</Text>
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen
        options={{
          title: '公众号订阅',
          headerStyle: { backgroundColor: theme.colors.surface },
          headerTintColor: theme.colors.onSurface,
        }}
      />

      <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
        <ScrollView
          style={styles.scrollView}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
        >
          {/* 说明卡片 */}
          <Card style={[styles.infoCard, { backgroundColor: theme.colors.primaryContainer }]}>
            <Card.Content>
              <View style={styles.infoRow}>
                <MaterialCommunityIcons
                  name="wechat"
                  size={24}
                  color={theme.colors.onPrimaryContainer}
                />
                <Text
                  variant="bodyMedium"
                  style={[styles.infoText, { color: theme.colors.onPrimaryContainer }]}
                >
                  订阅微信公众号后，系统会通过 RSSHub 自动采集文章，纳入每日财经播报。
                  每个公众号只需设置一次 biz 参数。
                </Text>
              </View>
            </Card.Content>
          </Card>

          {/* 已订阅列表 */}
          <Text
            variant="titleMedium"
            style={[styles.sectionTitle, { color: theme.colors.primary }]}
          >
            已订阅 ({accounts.length})
          </Text>

          {accounts.length === 0 ? (
            <Card style={styles.emptyCard}>
              <Card.Content style={styles.center}>
                <MaterialCommunityIcons
                  name="newspaper-variant-outline"
                  size={48}
                  color={theme.colors.outline}
                />
                <Text style={{ marginTop: 12, color: theme.colors.outline }}>
                  暂无订阅，点击 + 添加公众号
                </Text>
              </Card.Content>
            </Card>
          ) : (
            accounts.map((account) => (
              <Card key={account.id} style={styles.accountCard}>
                <Card.Content>
                  <View style={styles.accountHeader}>
                    <View style={styles.accountInfo}>
                      <View style={styles.nameRow}>
                        <Text variant="titleSmall" style={{ flex: 1 }}>
                          {account.name}
                        </Text>
                        <Chip
                          compact
                          textStyle={{ fontSize: 10 }}
                          style={{ height: 24 }}
                        >
                          {account.category}
                        </Chip>
                        {account.is_preset && (
                          <Chip
                            compact
                            textStyle={{ fontSize: 10, color: theme.colors.primary }}
                            style={{ height: 24, marginLeft: 4 }}
                          >
                            预置
                          </Chip>
                        )}
                      </View>
                      {account.description && (
                        <Text
                          variant="bodySmall"
                          style={{ color: theme.colors.outline, marginTop: 4 }}
                          numberOfLines={1}
                        >
                          {account.description}
                        </Text>
                      )}
                      <View style={styles.statsRow}>
                        <Text
                          variant="labelSmall"
                          style={{ color: theme.colors.outline }}
                        >
                          累计 {account.total_articles} 篇
                          {account.last_fetched_at &&
                            ` · 最近采集: ${new Date(account.last_fetched_at).toLocaleDateString()}`}
                          {account.fetch_fail_count > 2 &&
                            ` · ⚠️ 连续失败 ${account.fetch_fail_count} 次`}
                        </Text>
                      </View>
                    </View>
                    <Switch
                      value={account.enabled}
                      onValueChange={() => handleToggle(account)}
                      color={theme.colors.primary}
                    />
                  </View>

                  <Divider style={{ marginVertical: 8 }} />

                  <View style={styles.actionRow}>
                    <Button
                      mode="text"
                      compact
                      icon="test-tube"
                      loading={testingId === account.id}
                      onPress={() => handleTestFetch(account)}
                    >
                      测试
                    </Button>
                    <Button
                      mode="text"
                      compact
                      icon="delete-outline"
                      textColor={theme.colors.error}
                      onPress={() => handleDelete(account)}
                    >
                      删除
                    </Button>
                  </View>
                </Card.Content>
              </Card>
            ))
          )}

          {/* 可添加的预置公众号 */}
          {availablePresets.length > 0 && (
            <>
              <Text
                variant="titleMedium"
                style={[styles.sectionTitle, { color: theme.colors.primary }]}
              >
                推荐公众号
              </Text>
              <Text
                variant="bodySmall"
                style={[styles.sectionSubtitle, { color: theme.colors.outline }]}
              >
                点击快速添加
              </Text>

              <View style={styles.presetGrid}>
                {availablePresets.map((preset) => (
                  <Card
                    key={preset.biz}
                    style={styles.presetCard}
                    onPress={() => {
                      Alert.alert(
                        '添加公众号',
                        `添加「${preset.name}」？\n${preset.description}`,
                        [
                          { text: '取消', style: 'cancel' },
                          {
                            text: '添加',
                            onPress: async () => {
                              try {
                                await api.addWechatAccount({
                                  name: preset.name,
                                  biz: preset.biz,
                                  description: preset.description,
                                  category: preset.category,
                                });
                                await loadAccounts();
                                showSnack(`已添加 ${preset.name}`);
                              } catch (e) {
                                showSnack('添加失败');
                              }
                            },
                          },
                        ]
                      );
                    }}
                  >
                    <Card.Content style={styles.presetContent}>
                      <Text variant="bodyMedium" numberOfLines={1}>
                        {preset.name}
                      </Text>
                      <Text
                        variant="labelSmall"
                        style={{ color: theme.colors.outline }}
                        numberOfLines={1}
                      >
                        {preset.description}
                      </Text>
                    </Card.Content>
                  </Card>
                ))}
              </View>
            </>
          )}

          <View style={{ height: 80 }} />
        </ScrollView>

        {/* 添加按钮 */}
        <FAB
          icon="plus"
          style={[styles.fab, { backgroundColor: theme.colors.primary }]}
          color={theme.colors.onPrimary}
          onPress={() => {
            resetAddForm();
            setAddDialogVisible(true);
          }}
        />

        {/* 添加对话框 */}
        <Portal>
          <Dialog
            visible={addDialogVisible}
            onDismiss={() => setAddDialogVisible(false)}
            style={{ maxHeight: '80%' }}
          >
            <Dialog.Title>添加公众号</Dialog.Title>
            <Dialog.ScrollArea style={{ paddingHorizontal: 0 }}>
              <ScrollView style={{ paddingHorizontal: 24 }}>
                {/* 模式切换 */}
                <View style={styles.modeRow}>
                  <Chip
                    selected={addMode === 'link'}
                    onPress={() => setAddMode('link')}
                    style={styles.modeChip}
                  >
                    从链接提取
                  </Chip>
                  <Chip
                    selected={addMode === 'manual'}
                    onPress={() => setAddMode('manual')}
                    style={styles.modeChip}
                  >
                    手动填写
                  </Chip>
                </View>

                {addMode === 'link' ? (
                  <>
                    <Text variant="bodySmall" style={{ marginBottom: 8, color: theme.colors.outline }}>
                      在微信中打开该公众号的任意文章 → 分享 → 复制链接 → 粘贴到下方
                    </Text>
                    <TextInput
                      label="微信文章链接"
                      value={linkInput}
                      onChangeText={setLinkInput}
                      mode="outlined"
                      multiline
                      numberOfLines={3}
                      style={{ marginBottom: 12 }}
                      placeholder="https://mp.weixin.qq.com/s?__biz=..."
                    />
                    <Button
                      mode="contained"
                      loading={extracting}
                      onPress={handleExtractBiz}
                      style={{ marginBottom: 16 }}
                    >
                      提取 biz 参数
                    </Button>
                    {newBiz ? (
                      <Text variant="bodySmall" style={{ color: theme.colors.primary, marginBottom: 8 }}>
                        ✅ 已提取: {newBiz}，请填写公众号名称后确认添加
                      </Text>
                    ) : null}
                  </>
                ) : null}

                <TextInput
                  label="公众号名称 *"
                  value={newName}
                  onChangeText={setNewName}
                  mode="outlined"
                  style={{ marginBottom: 12 }}
                  placeholder="如：泽平宏观"
                />

                {addMode === 'manual' && (
                  <TextInput
                    label="biz 参数 *"
                    value={newBiz}
                    onChangeText={setNewBiz}
                    mode="outlined"
                    style={{ marginBottom: 12 }}
                    placeholder="如：MzA4NTI0MDY3OQ=="
                  />
                )}

                <TextInput
                  label="描述（可选）"
                  value={newDesc}
                  onChangeText={setNewDesc}
                  mode="outlined"
                  style={{ marginBottom: 12 }}
                  placeholder="如：任泽平团队宏观经济解读"
                />

                <View style={styles.categoryRow}>
                  {['财经', '宏观', '行业', '券商', '科技', '其他'].map((cat) => (
                    <Chip
                      key={cat}
                      selected={newCategory === cat}
                      onPress={() => setNewCategory(cat)}
                      style={styles.catChip}
                      compact
                    >
                      {cat}
                    </Chip>
                  ))}
                </View>
              </ScrollView>
            </Dialog.ScrollArea>
            <Dialog.Actions>
              <Button onPress={() => setAddDialogVisible(false)}>取消</Button>
              <Button onPress={handleAdd}>添加</Button>
            </Dialog.Actions>
          </Dialog>
        </Portal>

        {/* 测试结果对话框 */}
        <Portal>
          <Dialog
            visible={testDialogVisible}
            onDismiss={() => setTestDialogVisible(false)}
          >
            <Dialog.Title>
              采集测试 - {testResult?.account_name}
            </Dialog.Title>
            <Dialog.ScrollArea>
              <ScrollView style={{ paddingHorizontal: 24, maxHeight: 300 }}>
                {testResult?.status === 'success' ? (
                  <>
                    <Text
                      variant="bodyMedium"
                      style={{ color: theme.colors.primary, marginBottom: 12 }}
                    >
                      ✅ 获取到 {testResult.article_count} 篇文章
                    </Text>
                    {testResult.articles?.map((article: any, idx: number) => (
                      <View key={idx} style={styles.testArticle}>
                        <Text variant="bodySmall" style={{ fontWeight: 'bold' }}>
                          {idx + 1}. {article.title}
                        </Text>
                        <Text
                          variant="labelSmall"
                          style={{ color: theme.colors.outline, marginTop: 2 }}
                          numberOfLines={2}
                        >
                          {article.summary}
                        </Text>
                      </View>
                    ))}
                  </>
                ) : (
                  <Text style={{ color: theme.colors.error }}>
                    ❌ {testResult?.message || '未获取到文章'}
                  </Text>
                )}
              </ScrollView>
            </Dialog.ScrollArea>
            <Dialog.Actions>
              <Button onPress={() => setTestDialogVisible(false)}>关闭</Button>
            </Dialog.Actions>
          </Dialog>
        </Portal>

        {/* Snackbar */}
        <Snackbar
          visible={snackVisible}
          onDismiss={() => setSnackVisible(false)}
          duration={2000}
        >
          {snackMessage}
        </Snackbar>
      </View>
    </>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scrollView: {
    flex: 1,
    padding: 16,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  infoCard: {
    marginBottom: 16,
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  infoText: {
    flex: 1,
    lineHeight: 20,
  },
  sectionTitle: {
    marginTop: 16,
    marginBottom: 4,
    fontWeight: 'bold',
  },
  sectionSubtitle: {
    marginBottom: 12,
  },
  accountCard: {
    marginBottom: 12,
  },
  accountHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  accountInfo: {
    flex: 1,
    marginRight: 12,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  statsRow: {
    marginTop: 6,
  },
  actionRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 8,
  },
  presetGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  presetCard: {
    width: '48%',
  },
  presetContent: {
    paddingVertical: 8,
  },
  fab: {
    position: 'absolute',
    right: 16,
    bottom: 16,
  },
  modeRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 16,
  },
  modeChip: {},
  categoryRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 16,
  },
  catChip: {},
  testArticle: {
    marginBottom: 12,
    paddingBottom: 8,
    borderBottomWidth: 0.5,
    borderBottomColor: '#333',
  },
  emptyCard: {
    marginVertical: 12,
    paddingVertical: 24,
  },
});
